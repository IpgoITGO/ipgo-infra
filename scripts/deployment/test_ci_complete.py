"""합성 CI만 사용: 배포·네트워크·실제 gh/router 호출 없음."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import session
import worklog


class CiCompleteTests(unittest.TestCase):
    def fixture(self, directory, change=None, fail_watch=False):
        worklog.start(directory, "ci-fixture", provenance="synthetic")
        worklog.record(directory, "stage", stage="validation", kind="work", outcome="completed")
        plan = {"repo": "owner/server", "run_id": 17, "sha": "a" * 40, "branch": "dev",
                "event": "push", "workflow": ".github/workflows/test.yml", "jobs": ["test", "arm-test"]}
        path = directory / "ci-plan.json"
        session.save(path, plan)
        run = {"id": 17, "head_sha": "a" * 40, "head_branch": "dev", "event": "push",
               "path": plan["workflow"], "status": "completed", "conclusion": "success", "html_url": "https://example.test/run/17"}
        jobs = {"total_count": 2, "jobs": [{"name": name, "status": "completed", "conclusion": "success",
                 "completed_at": "2026-01-01T00:00:00Z"} for name in plan["jobs"]]}
        if change:
            change(run, jobs)
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            if fail_watch:
                raise subprocess.CalledProcessError(1, args, stderr="synthetic request failure")
            self.assertEqual(args[:2], ["gh", "api"])
            return subprocess.CompletedProcess(args, 0, json.dumps(jobs if "/jobs?" in args[2] else run), "")
        return path, runner, calls

    def test_collects_exact_run_once_and_advances_without_human_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "packet"
            plan, runner, calls = self.fixture(directory)
            result = session.ci_complete(directory, plan, runner)
            self.assertEqual(len(calls), 2)
            self.assertTrue(result["validation_passed"])
            self.assertFalse(result["authorization_granted"])
            self.assertEqual(result["human_review"], "pending")
            self.assertEqual(worklog.transact(directory, lambda _: None)[-1]["stage"], "documentation")
            with self.assertRaises(ValueError):
                session.ci_complete(directory, plan, runner)
            self.assertEqual(len(calls), 2)

    def test_identity_and_required_job_failures_preserve_validation_stage(self):
        changes = [lambda r, j: r.update(head_sha="b" * 40), lambda r, j: r.update(event="workflow_dispatch"),
                   lambda r, j: r.update(head_branch="main"), lambda r, j: r.update(path=".github/workflows/deploy.yml"),
                   lambda r, j: r.update(conclusion="failure"), lambda r, j: j["jobs"].pop(),
                   lambda r, j: j.update(total_count=101), lambda r, j: j["jobs"][0].update(conclusion="skipped"),
                   lambda r, j: j["jobs"][0].update(conclusion="failure"),
                   lambda r, j: j["jobs"][0].update(name="unexpected")]
        for change in changes:
            with self.subTest(change=changes.index(change)), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp) / "packet"
                plan, runner, _ = self.fixture(directory, change)
                with self.assertRaises(ValueError):
                    session.ci_complete(directory, plan, runner)
                self.assertFalse((directory / "ci-validation.json").exists())
                self.assertEqual(worklog.transact(directory, lambda _: None)[-1]["stage"], "validation")

    def test_failed_watch_keeps_original_and_never_queries_or_reports_success(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "packet"
            plan, runner, calls = self.fixture(directory, fail_watch=True)
            with self.assertRaises(subprocess.CalledProcessError):
                session.ci_complete(directory, plan, runner)
            self.assertEqual(len(calls), 1)
            self.assertTrue((directory / "ci-watch.log").exists())
            self.assertFalse((directory / "ci-validation.json").exists())

    def test_invalid_plan_is_rejected_before_any_external_call(self):
        for field, value in [("repo", "x; echo bad"), ("sha", "short"), ("run_id", True),
                             ("jobs", []), ("jobs", ["test", "test"]), ("workflow", ".github/workflows/deploy.yml")]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp) / "packet"
                plan, runner, calls = self.fixture(directory)
                data = session.read(plan); data[field] = value; plan.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    session.ci_complete(directory, plan, runner)
                self.assertEqual(calls, [])


    def test_plan_mutation_during_wait_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "packet"
            plan, runner, _ = self.fixture(directory)
            def changed(args, **kwargs):
                result = runner(args, **kwargs)
                if "/jobs?" not in args[2]:
                    plan.write_text(plan.read_text() + " ")
                return result
            with self.assertRaises(ValueError):
                session.ci_complete(directory, plan, changed)
            self.assertFalse((directory / "ci-validation.json").exists())

    def test_cli_contract_accepts_plan_option_and_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "packet"
            plan, _, _ = self.fixture(directory)
            data = session.read(plan); data["sha"] = "invalid"; plan.write_text(json.dumps(data))
            result = subprocess.run([__import__("sys").executable, str(Path(session.__file__)), "ci-complete",
                                     str(directory), "--plan", str(plan)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["state"], "BLOCKED")
            self.assertNotIn("usage:", result.stderr)


    def test_running_ci_waits_five_seconds_and_fetches_jobs_only_once(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "packet"
            plan, runner, calls = self.fixture(directory)
            reads = 0
            def pending(args, **kwargs):
                nonlocal reads
                result = runner(args, **kwargs)
                if "/jobs?" not in args[2]:
                    reads += 1
                    if reads == 1:
                        value = json.loads(result.stdout); value.update(status="in_progress", conclusion=None)
                        result.stdout = json.dumps(value)
                return result
            with patch.object(session.time, "sleep") as sleep:
                facts = session.ci_complete(directory, plan, pending)
            sleep.assert_called_once_with(5)
            self.assertEqual(len(calls), 3)
            self.assertEqual(sum("/jobs?" in c[2] for c in calls), 1)
            profile = facts["profile"]
            self.assertEqual(profile["api_calls"], 3)
            for key in ("wall_seconds", "python_cpu_seconds", "gh_cpu_seconds", "cli_non_cpu_seconds", "poll_sleep_seconds", "other_non_cpu_seconds"):
                self.assertGreaterEqual(profile[key], 0)

    def test_wrong_identity_never_waits_or_fetches_jobs(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "packet"
            plan, runner, calls = self.fixture(directory, lambda r, j: r.update(head_sha="b" * 40, status="in_progress"))
            with patch.object(session.time, "sleep") as sleep, self.assertRaises(ValueError):
                session.ci_complete(directory, plan, runner)
            sleep.assert_not_called()
            self.assertEqual(len(calls), 1)
            self.assertTrue((directory / "ci-run.json").exists())


if __name__ == "__main__":
    unittest.main()

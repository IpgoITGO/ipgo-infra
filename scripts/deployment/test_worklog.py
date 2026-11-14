"""합성 시각·로컬 파일만 사용한다. 실제 배포나 절약 실측이 아니다."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import worklog


def at(seconds):
    return f"2026-11-11T00:{seconds // 60:02d}:{seconds % 60:02d}Z"


class WorklogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "session"
        worklog.start(self.directory, "synthetic-test", "synthetic", at=at(0))
        self.artifact = Path(self.temp.name) / "ci.json"
        self.artifact.write_text('{"state":"passed"}')

    def stage(self, stage, seconds, **kwargs):
        return worklog.record(self.directory, "stage", at=at(seconds), stage=stage,
                              kind=kwargs.pop("kind", "work"),
                              outcome=kwargs.pop("outcome", "completed"), **kwargs)

    def check(self, seconds, **kwargs):
        fields = {"name": "source-ci", "scope": "server:source-sha:dev:v1", "boundary": "immutable",
                  "action": "executed", "reason": "initial", "result": "passed",
                  "evidence": worklog.evidence(self.artifact)}
        fields.update(kwargs)
        return worklog.record(self.directory, "check", at=at(seconds), **fields)

    def test_partitions_work_wait_rework_and_keeps_failure(self):
        self.stage("implementation", 10)
        self.stage("validation", 30)
        self.stage("implementation", 40, kind="rework", outcome="failed", reason="previous_failure")
        self.stage("approval", 55, kind="approval_wait")
        self.stage("deployment", 75, kind="execution_wait")
        self.stage("documentation", 100)
        worklog.record(self.directory, "finish", at=at(110), outcome="completed")
        result = worklog.report(self.directory)
        self.assertEqual(result["total_seconds"], 110)
        self.assertEqual(sum(result["stage_seconds"].values()), 110)
        self.assertEqual(result["stage_seconds"]["implementation"], 35)
        self.assertEqual(result["kind_seconds"], {"work": 50, "rework": 15, "approval_wait": 20, "execution_wait": 25})
        self.assertEqual(result["intervals"][2]["outcome"], "failed")
        self.assertEqual(result["provenance"], "synthetic")
        self.assertEqual(result["actual_savings"], "not_measured")
        self.assertFalse(result["authorization_granted"])

    def test_single_service_and_zero_time_skip_need_no_fake_run(self):
        self.stage("deployment", 20, target="client")
        worklog.record(self.directory, "skip", at=at(21), target="ai", reason="unchanged",
                       evidence=worklog.evidence(self.artifact))
        worklog.record(self.directory, "finish", at=at(40), outcome="completed")
        report = worklog.report(self.directory)
        self.assertEqual(report["stage_seconds"]["deployment"], 20)
        self.assertEqual(report["target_seconds"], {"client": 20})
        self.assertEqual(len(report["skipped"]), 1)
        with self.assertRaises(ValueError):
            worklog.record(self.directory, "stage", at=at(41), stage="deployment", kind="work", outcome="completed")

    def test_reexecution_requires_reason_and_check_events_do_not_double_count(self):
        self.check(5)
        for reason in (None, "initial"):
            with self.assertRaises(ValueError):
                self.check(10, reason=reason)
        self.check(10, reason="mandatory_boundary")
        report = worklog.report(self.directory, at=at(20))
        self.assertEqual(report["total_seconds"], 20)
        self.assertEqual(report["stage_seconds"], {"preparation": 20})
        self.assertEqual(report["repeated_check_names"], {"source-ci": 2})

    def test_reuse_rejects_changed_missing_failed_and_fresh_boundary_evidence(self):
        first = self.check(5)
        self.check(10, action="reused", reference=first["seq"])
        for changes in ({"scope": "server:new-source:dev:v1"}, {"evidence": None},
                        {"boundary": "write_guard"}, {"boundary": "post_change"}):
            with self.assertRaises(ValueError):
                self.check(12, action="reused", reference=first["seq"], **changes)
        self.artifact.write_text('{"state":"changed"}')
        with self.assertRaises(ValueError):
            self.check(12, action="reused", reference=first["seq"])
        self.artifact.write_text('{"state":"passed"}')
        self.check(13, result="failed", reason="previous_failure")
        with self.assertRaises(ValueError):
            self.check(14, action="reused", reference=first["seq"])

    def test_newer_changed_evidence_prevents_reusing_old_success(self):
        first = self.check(5)
        other = Path(self.temp.name) / "new.json"
        other.write_text('{"state":"new-evidence"}')
        self.check(10, reason="source_changed", evidence=worklog.evidence(other))
        with self.assertRaises(ValueError):
            self.check(11, action="reused", reference=first["seq"])

    def test_clock_reversal_naive_time_and_duplicate_start_preserve_original(self):
        before = (self.directory / "events.jsonl").read_bytes()
        with self.assertRaises(FileExistsError):
            worklog.start(self.directory, "duplicate", at=at(1))
        with self.assertRaises(ValueError):
            self.stage("validation", -1)
        with self.assertRaises(ValueError):
            worklog.record(self.directory, "finish", at="2026-11-11T00:00:01", outcome="failed")
        self.assertEqual((self.directory / "events.jsonl").read_bytes(), before)

    def test_incomplete_journal_is_not_silently_repaired(self):
        path = self.directory / "events.jsonl"
        with path.open("a") as stream:
            stream.write('{"partial":')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.stage("validation", 20)
        self.assertEqual(path.read_bytes(), before)

    def test_file_permissions_and_symlink_rejection(self):
        self.assertEqual((self.directory / "events.jsonl").stat().st_mode & 0o777, 0o600)
        link = Path(self.temp.name) / "link.json"
        link.symlink_to(self.artifact)
        with self.assertRaises(ValueError):
            worklog.evidence(link)
        secret = Path(self.temp.name) / ".env"
        secret.write_text("not-a-real-secret")
        with self.assertRaises(ValueError):
            worklog.evidence(secret)
        (self.directory / "events.jsonl").chmod(0o644)
        with self.assertRaises(ValueError):
            worklog.report(self.directory, at=at(1))

    def test_partial_in_progress_and_failed_finish_are_not_success_samples(self):
        other = Path(self.temp.name) / "partial"
        worklog.start(other, "partial", coverage="partial", at=at(0))
        result = worklog.report(other, at=at(20))
        self.assertEqual((result["coverage"], result["state"]), ("partial", "in_progress"))
        worklog.record(other, "finish", at=at(25), outcome="failed")
        self.assertEqual(worklog.report(other)["state"], "failed")

    def test_concurrent_writers_do_not_lose_events_and_cli_preserves_existing_report(self):
        script = str(Path(worklog.__file__))
        commands = [[sys.executable, script, "skip", str(self.directory), f"target-{i}",
                     "--reason", "not_requested"] for i in range(5)]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for command in commands]
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, (stdout, stderr))
        self.assertEqual(worklog.report(self.directory)["journal_event_count"], 6)
        out = Path(self.temp.name) / "report.json"
        command = [sys.executable, script, "report", str(self.directory), "--out", str(out)]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        original = out.read_bytes()
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(out.read_bytes(), original)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)

    def test_finish_report_includes_preparation_and_final_accounting_without_gaps(self):
        self.stage("documentation", 20)
        self.stage("finalization", 35)
        out = Path(self.temp.name) / "closed.json"
        with patch.object(worklog, "now", return_value=at(50)):
            result = worklog.save_report(self.directory, out, outcome="completed")
        saved = json.loads(out.read_text())
        self.assertEqual(saved, worklog.report(self.directory))
        self.assertEqual(saved["stage_seconds"], {"preparation": 20, "documentation": 15,
                                                 "finalization": 15})
        self.assertEqual(sum(saved["stage_seconds"].values()), saved["total_seconds"])
        self.assertEqual(result["total_seconds"], 50)
        self.assertEqual(saved["coverage"], "full")
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)

    def test_finish_output_collision_does_not_close_or_modify_the_journal(self):
        out = Path(self.temp.name) / "existing.json"
        out.write_text("original-report")
        before = (self.directory / "events.jsonl").read_bytes()
        with self.assertRaises(FileExistsError):
            worklog.save_report(self.directory, out, outcome="completed")
        self.assertEqual((self.directory / "events.jsonl").read_bytes(), before)
        self.assertEqual(out.read_text(), "original-report")

    def test_failed_finish_removes_only_its_new_empty_report(self):
        path = self.directory / "events.jsonl"
        with path.open("a") as stream:
            stream.write('{"partial":')
        before = path.read_bytes()
        out = Path(self.temp.name) / "not-created.json"
        with self.assertRaises(ValueError):
            worklog.save_report(self.directory, out, outcome="completed")
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(out.exists())

    def test_absolute_evidence_and_finish_cli_work_from_another_directory(self):
        script = str(Path(worklog.__file__))
        base = [sys.executable, script]
        check = base + ["check", str(self.directory), "--name", "http", "--scope", "server:dev:v1",
                        "--boundary", "post_change", "--result", "passed", "--reason", "initial"]
        bad = subprocess.run(check + ["--evidence", "ci.json"], cwd=self.temp.name, capture_output=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn(b"evidence path must be absolute", bad.stderr)
        self.assertEqual(worklog.report(self.directory)["journal_event_count"], 1)
        good = subprocess.run(check + ["--evidence", str(self.artifact)],
                              cwd=self.temp.name, capture_output=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        out = Path(self.temp.name) / "cli-closed.json"
        closed = subprocess.run(base + ["finish", str(self.directory), "--outcome", "completed",
                                       "--out", str(out)], cwd=self.temp.name, capture_output=True)
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertEqual(json.loads(out.read_text())["state"], "completed")

    def test_relative_report_is_rejected_before_finishing(self):
        before = (self.directory / "events.jsonl").read_bytes()
        with self.assertRaisesRegex(ValueError, "report path must be absolute"):
            worklog.save_report(self.directory, "relative.json", outcome="completed")
        self.assertEqual((self.directory / "events.jsonl").read_bytes(), before)

    def test_final_report_compares_validation_record_and_close_once(self):
        # Packet fields simulate real-record schema; this test itself is synthetic.
        before = {"state": "completed", "coverage": "full", "provenance": "actual",
                  "started_at": at(0), "stage_seconds": {"documentation": 20, "finalization": 10},
                  "intervals": [{"stage": "documentation", "started_at": at(40)}]}
        baseline = Path(self.temp.name) / "baseline.json"
        previous_run = Path(self.temp.name) / "run.json"
        baseline.write_text(json.dumps(before)); previous_run.write_text(json.dumps({"updated_at": at(10)}))
        config = Path(self.temp.name) / "compare.json"
        config.write_text(json.dumps({"summary": str(baseline), "run": str(previous_run),
                                      "same_scope_confirmed": False}))
        (self.directory / "client-observation.json").write_text(json.dumps({"run": {"updated_at": at(15)}}))
        # The workflow under test reads simulated actual packet metadata.
        journal = self.directory / "events.jsonl"
        journal.write_text(journal.read_text().replace('"provenance": "synthetic"', '"provenance": "actual"'))
        self.stage("documentation", 35); self.stage("finalization", 45)
        output = Path(self.temp.name) / "compared.json"
        with patch.object(worklog, "now", return_value=at(50)):
            worklog.save_report(self.directory, output, outcome="completed", compare=config)
        result = json.loads(output.read_text())["timing_comparison"]
        self.assertEqual(result["state"], "REFERENCE_ONLY")
        self.assertEqual([r["current_seconds"] for r in result["rows"]], [20, 10, 5])
        self.assertTrue(all(r["reduction_percent"] is None for r in result["rows"]))
        self.assertFalse(result["causal_savings_proven"])

    def test_non_deployment_task_is_not_an_effectiveness_sample(self):
        config = Path(self.temp.name) / "scope.json"
        config.write_text('{}')
        output = Path(self.temp.name) / "no-sample.json"
        worklog.save_report(self.directory, output, outcome="completed", compare=config)
        self.assertEqual(json.loads(output.read_text())["timing_comparison"]["state"], "NOT_COMPARABLE")


if __name__ == "__main__":
    unittest.main()

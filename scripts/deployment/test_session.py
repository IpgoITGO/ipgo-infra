"""합성 단계 인계와 과거 기록 집계. 네트워크·실제 배포 없음."""
import asyncio
import copy
import json
import tempfile
import subprocess
import worklog
import unittest
from pathlib import Path

import review
import session
from test_review import fixture, collector, SHAS, REGION, CLUSTER


class SessionTests(unittest.TestCase):
    def populate(self, directory, component, bundle, log):
        for key in ("dispatch", "run", "jobs", "after"):
            session.save(directory / f"{component}-{key}.json", bundle[key])
        session.save(directory / f"{component}-job.log", log)
        if component == "server":
            session.save(directory / "server-http.json", bundle["http_health"])

    def test_handoff_reuses_verified_server_snapshot_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            server, log, aws = fixture()
            session.save(directory / "preflight.json", {"plan": server["plan"], "before": server["before"]})
            self.populate(directory, "server", server, log)
            self.assertFalse(session.handoff(directory, "server")["authorization_granted"])
            with self.assertRaises(review.Blocked): session.handoff(directory, "server")
            ai, ai_log, _ = fixture("ai")
            aws.install("ai", 2, SHAS["ai"])
            baseline = {s["name"]: s["td"] for s in server["after"]["services"]}
            ai["after"] = asyncio.run(collector(aws)(REGION, CLUSTER, baseline))
            self.populate(directory, "ai", ai, ai_log)
            self.assertEqual(session.handoff(directory, "ai")["state"], "VERIFIED_OBSERVATION")
            saved = session.read(directory / "ai-verify.json")
            self.assertEqual(saved["before"], server["after"])
            (directory / "server-job.log").write_text(log + "changed")
            with self.assertRaises(review.Blocked): session.handoff(directory, "ai")

    def test_failed_or_stale_evidence_never_produces_receipt(self):
        for problem in ("failed", "stale", "missing", "ai_first"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                bundle, log, _ = fixture()
                session.save(directory / "preflight.json", {"plan": bundle["plan"], "before": bundle["before"]})
                if problem == "failed": bundle["run"]["conclusion"] = "failure"
                if problem == "stale": bundle["after"]["observed_at"] = "2020-01-01T00:00:00Z"
                self.populate(directory, "server", bundle, log)
                if problem == "missing": (directory / "server-http.json").unlink()
                with self.assertRaises((review.Blocked, OSError)):
                    session.handoff(directory, "ai" if problem == "ai_first" else "server")
                self.assertFalse((directory / "server-receipt.json").exists())

    def test_three_run_audit_partitions_total_and_rejects_overlap(self):
        start = "2026-11-11T00:00:00Z"
        boundaries = [start] + [f"2026-11-11T00:0{i}:00Z" for i in range(1, 7)]
        phases = [{"name": n, "started_at": a, "finished_at": b, "status": "success"}
                  for n, a, b in zip(["preparation", "database", "server", "ai", "client", "final_verification_and_record"], boundaries, boundaries[1:])]
        def run(i, begin, end):
            return {"id": i, "status": "completed", "created_at": begin, "updated_at": end}
        bundle = {"started_at": start, "finished_at": boundaries[-1], "provenance": "synthetic", "phases": phases,
                  "server": {"run": run(1, boundaries[2], boundaries[3])},
                  "ai": {"run": run(2, boundaries[3], boundaries[4])}}
        client = run(3, boundaries[4], boundaries[5])
        result = session.audit(bundle, client)
        self.assertEqual(result["total_seconds"], 360)
        self.assertEqual(result["app_actions_seconds"], 180)
        self.assertEqual(sum(result["interval_seconds"].values()), 360)
        bad = copy.deepcopy(client);bad["created_at"] = boundaries[3]
        with self.assertRaises(review.Blocked): session.audit(bundle, bad)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.md"
            session.save(path, session.markdown(result))
            with self.assertRaises(FileExistsError): session.save(path, "overwrite history")



class LocalServerTests(unittest.TestCase):
    def local_fixture(self, root):
            directory, tree = root / 'packet', root / 'tree'
            directory.mkdir(); tree.mkdir()
            (tree / 'app.java').write_text('fixed source')
            session.save(directory / 'final-source-hashes.json', {'app.java': session.digest(tree / 'app.java')})
            (directory / 'java-finished.txt').write_text('2026-11-14T11:00:00+00:00')
            xml = tree / 'build/test-results/test'; xml.mkdir(parents=True)
            (xml / 'TEST-fixture.xml').write_text('<testsuite tests="2" failures="0" errors="0" skipped="0"/>')
            jar = tree / 'build/libs'; jar.mkdir()
            (jar / 'app.jar').write_bytes(b'synthetic fixture')
            return directory, tree

    def test_server_complete_collects_once_and_requires_human_review(self):
            with tempfile.TemporaryDirectory() as temp:
                directory, tree = self.local_fixture(Path(temp))
                result = session.server_complete(directory, tree, '2026-11-14T11:00:01+00:00', 0, 0)
                self.assertEqual(result['junit']['tests'], 2)
                self.assertEqual(result['human_review'], 'pending')
                self.assertFalse(result['authorization_granted'])
                self.assertTrue((directory / 'final-xml/TEST-fixture.xml').exists())
                original = (directory / 'server-validation.json').read_bytes()
                with self.assertRaises(ValueError):
                    session.server_complete(directory, tree, '2026-11-14T11:00:01+00:00', 0, 0)
                self.assertEqual((directory / 'server-validation.json').read_bytes(), original)

    def test_server_complete_rejects_failed_exit_or_changed_source(self):
            with tempfile.TemporaryDirectory() as temp:
                directory, tree = self.local_fixture(Path(temp))
                with self.assertRaises(ValueError):
                    session.server_complete(directory, tree, '2026-11-14T11:00:01+00:00', 1, 0)
                (tree / 'app.java').write_text('changed source')
                with self.assertRaises(ValueError):
                    session.server_complete(directory, tree, '2026-11-14T11:00:01+00:00', 0, 0)
                self.assertFalse((directory / 'server-validation.json').exists())

    def test_server_complete_rejects_bad_xml_or_missing_jar(self):
            for invalid in ('xml', 'jar'):
                with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temp:
                    directory, tree = self.local_fixture(Path(temp))
                    if invalid == 'xml':
                        (tree / 'build/test-results/test/TEST-fixture.xml').write_text(
                            '<testsuite tests="2" failures="1" errors="0" skipped="0"/>')
                    else:
                        (tree / 'build/libs/app.jar').unlink()
                    with self.assertRaises(ValueError):
                        session.server_complete(directory, tree, '2026-11-14T11:00:01+00:00', 0, 0)
                    self.assertFalse((directory / 'server-validation.json').exists())



class CloseTests(unittest.TestCase):
    def test_close_preserves_notices_and_reuses_confirmed_router_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "private"
            worklog.start(directory, "synthetic-close", provenance="synthetic")
            worklog.record(directory, "stage", stage="finalization", kind="work", outcome="completed", reason=None, target=None)
            session.save(directory / "completion.json", {"validation_passed": True})
            calls = []
            def runner(args, **kwargs):
                calls.append(args[1])
                value = {"event_id": "a" * 32, "status": "success", "validation": "passed"} if args[1] == "desktop-finish" else {
                    "pending_notices": ["synthetic"], "new_notices": [], "pending_notice_count": 1, "failed_refreshes": 0}
                return subprocess.CompletedProcess(args, 0, json.dumps(value), "")
            for _ in range(2):
                self.assertEqual(session.close_check(directory, "a" * 32, runner)["state"], "OUTPUT_NOTICE_PENDING")
            self.assertEqual(calls, ["desktop-finish", "output-report", "output-report"])
            self.assertFalse((directory / "summary.json").exists())
            reports = sorted(directory.glob("close-check-*.json"))
            self.assertEqual(len(reports), 2)
            first, second = [session.read(p) for p in reports]
            self.assertEqual([c["command"] for c in first["commands"]], ["desktop-finish", "output-report"])
            self.assertEqual([c["command"] for c in second["commands"]], ["output-report"])
            for report in (first, second):
                for command in report["commands"]:
                    self.assertGreaterEqual(command["wall_seconds"], 0)
                    self.assertGreaterEqual(command["python_cpu_seconds"], 0)
                    self.assertGreaterEqual(command["child_cpu_seconds"], 0)
                    self.assertTrue(Path(command["evidence"]["path"]).is_file())



if __name__ == "__main__":
    unittest.main()

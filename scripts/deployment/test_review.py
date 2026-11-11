"""합성 자료·가짜 AWS만 사용한다. 실제 배포/권한/사용자 업무 검증이 아니다."""
import ast
import asyncio
import copy
import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import review


ROOT = Path(__file__).parent
ACCOUNT = "123456789012"
REGION = "ap-northeast-2"
CLUSTER = "ipgo-dev-cluster"
SHAS = {"server": "a" * 40, "ai": "b" * 40}
DIGEST = "sha256:" + "c" * 64


def service_name(component):
    return "ipgo-dev-onebox-" + ("server" if component == "server" else "ai-api")


def definition(component, revision, image_sha):
    name = service_name(component)
    cname = "server" if component == "server" else "ai-api"
    arn = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{name}:{revision}"
    return {"taskDefinitionArn": arn, "family": name, "revision": revision,
            "containerDefinitions": [{"name": cname,
                "image": f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/ipgo-dev/{component}:{image_sha}-arm64",
                "environment": [{"name": "DO_NOT_DISCLOSE", "value": "private-value"}],
                "secrets": [{"name": "KEY", "valueFrom": "secret-reference"}],
                "healthCheck": {"command": ["CMD-SHELL", "curl http://127.0.0.1:" +
                    ("8080/actuator/health" if component == "server" else "8000/health")]}}]}


class FakeAWS:
    def __init__(self):
        self.definitions = {}
        self.current = {}
        self.calls = []
        for component in SHAS:
            self.install(component, 1, "d" * 40)

    def install(self, component, revision, sha):
        td = definition(component, revision, sha)
        self.definitions[td["taskDefinitionArn"]] = td
        self.current[service_name(component)] = td["taskDefinitionArn"]

    async def call(self, *, service_name, operation_name, region_name, params=None):
        self.calls.append(operation_name)
        self.assert_region = region_name == REGION
        if operation_name == "GetCallerIdentity":
            return {"Account": ACCOUNT}
        if operation_name == "DescribeRegions":
            return {"Regions": [{"RegionName": REGION}]}
        if operation_name == "ListServices":
            return {"serviceArns": list(self.current)}
        if operation_name == "DescribeServices":
            return {"services": [{"serviceName": n, "taskDefinition": arn,
                "desiredCount": 1, "runningCount": 1, "pendingCount": 0,
                "deploymentConfiguration": {"minimumHealthyPercent": 0, "maximumPercent": 100},
                "deployments": [{"status": "PRIMARY", "rolloutState": "COMPLETED",
                                 "failedTasks": 0, "taskDefinition": arn}]}
                for n, arn in self.current.items()]}
        if operation_name == "ListTasks":
            return {"taskArns": list(self.current)}
        if operation_name == "DescribeTasks":
            return {"tasks": [{"group": "service:" + n, "taskDefinitionArn": arn,
                "lastStatus": "RUNNING", "healthStatus": "HEALTHY", "containers": [{
                    "name": self.definitions[arn]["containerDefinitions"][0]["name"],
                    "image": self.definitions[arn]["containerDefinitions"][0]["image"],
                    "imageDigest": DIGEST, "healthStatus": "HEALTHY"}]}
                for n, arn in self.current.items()]}
        if operation_name == "DescribeTaskDefinition":
            return {"taskDefinition": copy.deepcopy(self.definitions[params["taskDefinition"]])}
        raise AssertionError("Unapproved API: " + operation_name)


def collector(fake):
    ns = {"call_boto3": fake.call, "datetime": dt, "asyncio": asyncio}
    exec(compile((ROOT / "collect_aws.py").read_text(), "collect_aws.py", "exec"), ns)
    return ns["collect_deployment"]


def fixture(component="server"):
    aws = FakeAWS()
    collect = collector(aws)
    before = asyncio.run(collect(REGION, CLUSTER))
    baselines = {s["name"]: s["td"] for s in before["services"]}
    aws.install(component, 2, SHAS[component])
    after = asyncio.run(collect(REGION, CLUSTER, baselines))
    plan = {"account": ACCOUNT, "region": REGION, "cluster": CLUSTER}
    for part in SHAS:
        plan[part] = {"source_sha": SHAS[part], "workflow_sha": SHAS[part],
                      "workflow_id": 10, "environment_id": 20}
    run = {"id": 30, "repository": {"full_name": "IpgoITGO/ipgo-" + component},
           "head_sha": SHAS[component], "head_branch": "dev", "event": "workflow_dispatch",
           "run_attempt": 1, "workflow_id": 10, "path": ".github/workflows/deploy-dev.yml",
           "status": "completed", "conclusion": "success"}
    names = ["Verify approved source CI before AWS access", "Verify AWS read prerequisites before deployment writes",
             "Verify immutable image before deployment", "Verify deployed task identity and application health",
             "Wait for exact candidate rollout" if component == "server" else "Wait for exact API candidate rollout"]
    bundle = {"component": component, "plan": plan, "before": before, "after": after, "run": run,
              "dispatch": {"ref": "dev", "inputs": {"source_sha": SHAS[component], "expected_sha": SHAS[component]}},
              "jobs": {"total_count": 1, "jobs": [{"run_id": 30, "conclusion": "success",
                        "steps": [{"name": n, "conclusion": "success"} for n in names]}]},
              "http_health": {"observed_at": after["observed_at"], "http_status": 200, "body": {"status": "UP"}}}
    log = '\n'.join("2026-11-10T12:00:00Z " + json.dumps(r) for r in [
        {"image_exists": True, "digest": DIGEST},
        {"api": {"replicas": 1, "application_health_checked": True},
         "external_http": "passed" if component == "server" else "not_exposed_agent_http_health_checked"}])
    return bundle, log, aws


class ReviewTests(unittest.TestCase):
    def test_collector_reports_environment_names_without_values(self):
        aws = FakeAWS()
        collect = collector(aws)
        before = asyncio.run(collect(REGION, CLUSTER))
        baselines = {s["name"]: s["td"] for s in before["services"]}
        aws.install("server", 2, SHAS["server"])
        td = aws.definitions[aws.current[service_name("server")]]
        td["containerDefinitions"][0]["environment"][0]["value"] = "changed-private-value"
        after = asyncio.run(collect(REGION, CLUSTER, baselines))
        row = next(s for s in after["services"] if s["name"] == service_name("server"))
        self.assertIn("container.server.environment.DO_NOT_DISCLOSE", row["changed_paths"])
        self.assertNotIn("changed-private-value", json.dumps(after))

    def test_exact_approved_start_change_rejects_other_environment_drift(self):
        b, log, _ = fixture()
        old, new = b["before"]["services"][0], b["after"]["services"][0]
        setting = "IPGO_INSIGHT_DEMO_STARTS_AT"
        old["settings"][setting] = "2026-11-10T00:00:00Z"
        new["settings"][setting] = "2026-11-11T00:00:00Z"
        new["changed_paths"].append("container.server.environment." + setting)
        with self.assertRaises(review.Blocked): review.runtime_gate(b, log)
        b["approved_server_start_change"] = {"from": old["settings"][setting], "to": new["settings"][setting], "approval_reference": "synthetic-explicit-approval"}
        self.assertEqual(review.runtime_gate(b, log)["state"], "VERIFIED_OBSERVATION")
        new["changed_paths"].append("container.server.environment.PRIVATE_UNAPPROVED")
        with self.assertRaises(review.Blocked): review.runtime_gate(b, log)

    def test_preflight_exact_sources_ci_and_baseline(self):
        b, _, _ = fixture()
        b["sources"] = {}
        for component in SHAS:
            ci = {"id": 40, "repository": {"full_name": "IpgoITGO/ipgo-" + component},
                  "head_sha": SHAS[component], "head_branch": "dev", "event": "push",
                  "path": ".github/workflows/test.yml", "status": "completed", "conclusion": "success"}
            names = ["test", "container", "deploy-contract", "arm-test" if component == "server" else "arm-capacity"]
            b["sources"][component] = {"branch": {"commit": {"sha": SHAS[component]}}, "ci_run": ci,
                                     "ci_jobs": {"total_count": 4, "jobs": [
                                         {"name": name, "run_id": 40, "conclusion": "success"} for name in names]}}
        self.assertFalse(review.baseline_gate(b)["authorization_granted"])
        for kind in ("branch", "ci", "runtime"):
            bad = copy.deepcopy(b)
            if kind == "branch":bad["sources"]["server"]["branch"]["commit"]["sha"] = "f" * 40
            if kind == "ci":bad["sources"]["ai"]["ci_jobs"]["jobs"][0]["conclusion"] = "failure"
            if kind == "runtime":bad["before"]["services"][0]["pending"] = 1
            with self.subTest(kind=kind), self.assertRaises(review.Blocked):review.baseline_gate(bad)

    def test_timing_requires_order_and_does_not_invent_savings(self):
        b = {"provenance": "synthetic", "started_at": "2026-11-10T12:00:00Z",
             "finished_at": "2026-11-10T12:10:00Z",
             "server": {"run": {"created_at": "2026-11-10T12:01:00Z", "updated_at": "2026-11-10T12:05:00Z"}},
             "ai": {"run": {"created_at": "2026-11-10T12:06:00Z", "updated_at": "2026-11-10T12:09:00Z"}}}
        result = review.timing_report(b)
        self.assertEqual(result["overall_seconds"], 600)
        self.assertEqual(result["actual_savings"], "not_measured")
        with self.assertRaises(review.Blocked):
            review.timing_report(b, require_full_pipeline=True)
        b["ai"]["run"]["created_at"] = "2026-11-10T12:04:00Z"
        with self.assertRaises(review.Blocked):review.timing_report(b)

    def test_full_pipeline_time_includes_db_client_and_final_record_without_holes(self):
        b = {"provenance": "synthetic", "started_at": "2026-11-10T12:00:00Z",
             "finished_at": "2026-11-10T12:10:00Z",
             "server": {"run": {"created_at": "2026-11-10T12:01:00Z", "updated_at": "2026-11-10T12:05:00Z"}},
             "ai": {"run": {"created_at": "2026-11-10T12:06:00Z", "updated_at": "2026-11-10T12:09:00Z"}}}
        names = ["preparation", "database", "server", "ai", "client", "final_verification_and_record"]
        times = ["00:00", "00:30", "01:00", "06:00", "09:00", "09:30", "10:00"]
        b["phases"] = [{"name": name, "status": "success", "started_at": "2026-11-10T12:" + a + "Z",
                        "finished_at": "2026-11-10T12:" + z + "Z"}
                       for name, a, z in zip(names, times, times[1:])]
        result = review.timing_report(b, require_full_pipeline=True)
        self.assertEqual(result["full_pipeline_seconds"], 600)
        self.assertEqual(sum(result["phase_seconds"].values()), 600)
        self.assertEqual(result["phase_seconds"]["database"], 30)
        self.assertEqual(result["phase_seconds"]["client"], 30)
        self.assertEqual(result["actual_savings"], "not_measured")
        skipped = copy.deepcopy(b)
        skipped["phases"][0]["finished_at"] = skipped["phases"][1]["finished_at"]
        skipped["phases"][1].update(started_at=skipped["phases"][1]["finished_at"],
                                     status="skipped", reason="already applied; read-only evidence recorded")
        self.assertEqual(review.timing_report(skipped, require_full_pipeline=True)["phase_seconds"]["database"], 0)
        del skipped["phases"][1]["reason"]
        with self.assertRaises(review.Blocked):
            review.timing_report(skipped, require_full_pipeline=True)
        for kind in ("gap", "overlap", "missing", "unfinished", "hidden_end", "outside_run"):
            bad = copy.deepcopy(b)
            if kind == "gap": bad["phases"][1]["started_at"] = "2026-11-10T12:00:31Z"
            if kind == "overlap": bad["phases"][1]["started_at"] = "2026-11-10T12:00:29Z"
            if kind == "missing": bad["phases"].pop(1)
            if kind == "unfinished": bad["phases"][1]["status"] = "in_progress"
            if kind == "hidden_end": bad["phases"][-1]["finished_at"] = "2026-11-10T12:09:59Z"
            if kind == "outside_run":
                bad["phases"][1]["finished_at"] = "2026-11-10T12:01:01Z"
                bad["phases"][2]["started_at"] = "2026-11-10T12:01:01Z"
            with self.subTest(kind=kind), self.assertRaises(review.Blocked):
                review.timing_report(bad)

    def test_collector_and_runtime_both_components(self):
        for component in SHAS:
            b, log, aws = fixture(component)
            result = review.runtime_gate(b, log)
            self.assertFalse(result["authorization_granted"])
            self.assertFalse(result["external_write_performed"])
            self.assertEqual(result["state"], "VERIFIED_OBSERVATION")
            self.assertNotIn("private-value", json.dumps(b["after"]))
            self.assertNotIn("secret-reference", json.dumps(b["after"]))
            self.assertTrue(aws.assert_region)

    def test_run_waiting_never_approves(self):
        b, _, _ = fixture()
        b["run"].update(status="waiting", conclusion=None)
        b["pending"] = [{"environment": {"id": 20, "name": "dev"}, "current_user_can_approve": True}]
        self.assertEqual(review.run_gate(b), "EXPLICIT_ENVIRONMENT_APPROVAL_REQUIRED")
        b["pending"][0]["environment"]["id"] = 21
        with self.assertRaises(review.Blocked): review.run_gate(b)

    def test_run_rejects_wrong_identity_failure_and_retry(self):
        for key, value in [("head_sha", "f" * 40), ("head_branch", "main"),
                           ("workflow_id", 99), ("run_attempt", 2), ("conclusion", "failure")]:
            b, _, _ = fixture();b["run"][key] = value
            with self.subTest(key=key), self.assertRaises(review.Blocked): review.run_gate(b)

    def test_skipped_or_missing_safety_steps_block(self):
        b, _, _ = fixture();b["jobs"]["jobs"][0]["steps"][0]["conclusion"] = "skipped"
        with self.assertRaises(review.Blocked): review.run_gate(b)

    def test_in_progress_not_redispatch_or_success(self):
        b, _, _ = fixture();b["run"].update(status="in_progress", conclusion=None)
        self.assertEqual(review.run_gate(b), "IN_PROGRESS_NO_REDISPATCH")
        with self.assertRaises(review.Blocked): review.run_gate(b, complete=True)

    def test_runtime_rejects_drift_partial_rollout_and_unhealthy(self):
        for key, value in [("pending", 1), ("http_health_check", False),
                           ("changed_paths", ["container.server.environment"]), ("baseline_td", "other"),
                           ("deployments", [{"status": "PRIMARY", "rollout": "IN_PROGRESS"}])]:
            b, log, _ = fixture();b["after"]["services"][1 if b["after"]["services"][0]["name"].endswith("ai-api") else 0][key] = value
            with self.subTest(key=key), self.assertRaises(review.Blocked): review.runtime_gate(b, log)

    def test_runtime_rejects_task_image_digest_unknown_health(self):
        for key, value in [("digest", "sha256:" + "e" * 64), ("image", "other"), ("health", "UNKNOWN")]:
            b, log, _ = fixture();b["after"]["tasks"][0]["containers"][0][key] = value
            with self.subTest(key=key), self.assertRaises(review.Blocked): review.runtime_gate(b, log)

    def test_other_service_change_and_wrong_account_block(self):
        b, log, _ = fixture();b["after"]["services"][1]["td"] += "0"
        with self.assertRaises(review.Blocked): review.runtime_gate(b, log)
        b, log, _ = fixture();b["after"]["account"] = "000000000000"
        with self.assertRaises(review.Blocked): review.runtime_gate(b, log)

    def test_stale_snapshot_http_and_missing_log_block(self):
        for alteration in ("aws", "http", "log"):
            b, log, _ = fixture()
            if alteration == "aws":b["after"]["observed_at"] = "2020-01-01T00:00:00Z"
            if alteration == "http":b["http_health"]["http_status"] = 500
            if alteration == "log":log = "no verification evidence"
            with self.subTest(alteration=alteration), self.assertRaises(review.Blocked): review.runtime_gate(b, log)

    def test_replay_label_does_not_grant_authorization(self):
        b, log, _ = fixture()
        b["before"]["observed_at"] = "2020-01-01T00:00:00Z"
        b["after"]["observed_at"] = "2020-01-01T00:02:00Z"
        self.assertEqual(review.runtime_gate(b, log, replay=True)["provenance"], "offline_replay")

    def test_cli_bad_input_never_echoes_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "bundle.json";p.write_text('{"private-value": true}')
            r = subprocess.run([sys.executable, str(ROOT / "review.py"), "run", str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertNotIn("private-value", r.stdout + r.stderr)

    def test_collector_source_has_no_imports_or_write_api(self):
        tree = ast.parse((ROOT / "collect_aws.py").read_text())
        self.assertFalse(any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr.startswith("__") for n in ast.walk(tree)))
        operations = {k.value.value for n in ast.walk(tree) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Name) and n.func.id == "call_boto3"
                      for k in n.keywords if k.arg == "operation_name"}
        self.assertEqual(operations, {"GetCallerIdentity", "DescribeRegions", "ListServices", "DescribeServices",
                                     "ListTasks", "DescribeTasks", "DescribeTaskDefinition"})

    def test_collector_partial_permission_and_pagination_block(self):
        for kind in ("permission", "pagination", "missing"):
            aws = FakeAWS(); original = aws.call
            async def incomplete(**kwargs):
                result = await original(**kwargs)
                if kind == "permission" and kwargs["operation_name"] == "DescribeTaskDefinition":
                    raise ValueError("private-value")
                if kind == "pagination" and kwargs["operation_name"] == "ListServices":
                    result["nextToken"] = "more"
                if kind == "missing" and kwargs["operation_name"] == "DescribeTasks":
                    result["tasks"] = []
                return result
            aws.call = incomplete
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                asyncio.run(collector(aws)(REGION, CLUSTER))


if __name__ == "__main__":
    unittest.main()

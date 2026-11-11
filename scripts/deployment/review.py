"""저장된 근거의 결정적 대조/요약. 네트워크·배포·승인·AWS SDK 호출 없음."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


class Blocked(ValueError):
    pass


def require(value, code):
    if not value:
        raise Blocked(code)


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fresh(snapshot, now):
    delta = (now - instant(snapshot["observed_at"])).total_seconds()
    require(0 <= delta <= 300, "EVIDENCE_STALE_OR_FUTURE")


def baseline_gate(bundle, now=None, replay=False):
    before, plan = bundle["before"], bundle["plan"]
    if not replay:
        fresh(before, now or datetime.now(timezone.utc))
    require(before["account"] == plan["account"] and before["region"] == plan["region"]
            and before["region_confirmed"] is True and before["cluster"] == plan["cluster"],
            "ACCOUNT_REGION_CLUSTER")
    require(all(s["pending"] == 0 and s["running"] == s["desired"]
                and len(s["deployments"]) == 1 and s["deployments"][0]["rollout"] == "COMPLETED"
                for s in before["services"]), "BASELINE_DEPLOYMENT_IN_PROGRESS")
    for component in ("server", "ai"):
        target, source = plan[component], bundle["sources"][component]
        require(re.fullmatch(r"[a-f0-9]{40}", target["source_sha"]), "FULL_SHA_REQUIRED")
        require(source["branch"]["commit"]["sha"] == target["workflow_sha"] == target["source_sha"],
                "DEV_CHANGED_REVIEW_REQUIRED")
        ci, jobs = source["ci_run"], source["ci_jobs"]
        require(ci["repository"]["full_name"] == "IpgoITGO/ipgo-" + component
                and ci["head_sha"] == target["source_sha"] and ci["head_branch"] == "dev"
                and ci["event"] == "push" and ci["path"] == ".github/workflows/test.yml"
                and ci["status"] == "completed" and ci["conclusion"] == "success", "CI_SOURCE")
        require(jobs["total_count"] == len(jobs["jobs"]) == 4
                and {j["name"] for j in jobs["jobs"]} == {
                    "test", "container", "deploy-contract", "arm-test" if component == "server" else "arm-capacity"}
                and all(j["run_id"] == ci["id"] and j["conclusion"] == "success" for j in jobs["jobs"]),
                "CI_JOBS")
        name = "ipgo-dev-onebox-" + ("server" if component == "server" else "ai-api")
        services = [s for s in before["services"] if s["name"] == name]
        require(len(services) == 1, "BASELINE_SERVICE")
        service = services[0]
        require((service["desired"], service["running"], service["pending"]) == (1, 1, 0)
                and len(service["deployments"]) == 1
                and service["deployments"][0]["rollout"] == "COMPLETED", "BASELINE_UNSTABLE")
        tasks = [t for t in before["tasks"] if t["service"] == name]
        require(len(tasks) == 1 and tasks[0]["td"] == service["td"]
                and tasks[0]["health"] == "HEALTHY", "BASELINE_TASK")
    return {"state": "BASELINE_CHECKED_REQUIRES_USER_APPROVAL", "authorization_granted": False,
            "provenance": "offline_replay" if replay else "provided_live_evidence"}


def run_gate(bundle, complete=False):
    component = bundle["component"]
    require(component in ("server", "ai"), "COMPONENT")
    target, run = bundle["plan"][component], bundle["run"]
    inputs = bundle["dispatch"]["inputs"]
    for key in ("source_sha", "workflow_sha"):
        require(re.fullmatch(r"[a-f0-9]{40}", target[key]), "FULL_SHA_REQUIRED")
    require(bundle["dispatch"]["ref"] == "dev", "DISPATCH_REF")
    require(inputs["source_sha"] == inputs["expected_sha"] == target["source_sha"],
            "DISPATCH_SHA")
    require(run["repository"]["full_name"] == "IpgoITGO/ipgo-" + component, "REPOSITORY")
    require(run["head_sha"] == target["workflow_sha"] and run["head_branch"] == "dev",
            "RUN_SHA_OR_BRANCH")
    require(run["event"] == "workflow_dispatch" and run["run_attempt"] == 1, "RUN_OR_ATTEMPT")
    require(run["workflow_id"] == target["workflow_id"], "WORKFLOW_ID")
    require(run["path"] == ".github/workflows/deploy-dev.yml", "WORKFLOW_PATH")
    require(isinstance(run["id"], int) and run["id"] > 0, "RUN_ID")
    if complete or run["status"] == "completed":
        require(run["status"] == "completed" and run["conclusion"] == "success", "RUN_NOT_SUCCESS")
        jobs = bundle["jobs"]["jobs"]
        require(len(jobs) == 1 and bundle["jobs"]["total_count"] == 1, "JOBS_INCOMPLETE")
        job = jobs[0]
        require(job["run_id"] == run["id"] and job["conclusion"] == "success", "JOB_NOT_SUCCESS")
        required = {"Verify approved source CI before AWS access",
                    "Verify AWS read prerequisites before deployment writes",
                    "Verify immutable image before deployment",
                    "Verify deployed task identity and application health",
                    "Wait for exact candidate rollout" if component == "server"
                    else "Wait for exact API candidate rollout"}
        successes = {s["name"] for s in job["steps"] if s["conclusion"] == "success"}
        require(required <= successes, "SAFETY_STEPS_INCOMPLETE")
        require(not any(s["conclusion"] in ("failure", "cancelled", "timed_out")
                        for s in job["steps"]), "STEP_FAILED")
        return "WORKFLOW_SUCCESS_REQUIRES_INDEPENDENT_RUNTIME_CHECK"
    if run["status"] == "waiting":
        pending = bundle["pending"]
        require(len(pending) == 1 and pending[0]["environment"]["name"] == "dev"
                and pending[0]["environment"]["id"] == target["environment_id"], "ENVIRONMENT")
        require(pending[0].get("current_user_can_approve") is True, "CANNOT_APPROVE")
        return ("EXPLICIT_ENVIRONMENT_APPROVAL_REQUIRED" if component == "server"
                else "SERVER_VERIFICATION_AND_EXPLICIT_ENVIRONMENT_APPROVAL_REQUIRED")
    require(run["status"] in ("queued", "in_progress", "requested", "pending"), "UNKNOWN_RUN_STATE")
    return "IN_PROGRESS_NO_REDISPATCH"


def verified_log(text, component):
    records = []
    for line in text.splitlines():
        match = re.match(r"^\ufeff?\S+Z (\{.*\})$", line)
        if match:
            try:
                records.append(json.loads(match[1]))
            except json.JSONDecodeError:
                pass
    digests = {r["digest"] for r in records if r.get("image_exists") is True and "digest" in r}
    require(len(digests) == 1, "IMAGE_VERIFICATION_LOG_MISSING_OR_AMBIGUOUS")
    digest = digests.pop()
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", digest), "DIGEST_FORMAT")
    health = [r for r in records if isinstance(r.get("api"), dict)
              and r["api"].get("application_health_checked") is True
              and r["api"].get("replicas") == 1]
    require(len(health) == 1, "WORKFLOW_HEALTH_LOG")
    require(health[0].get("external_http") in (
        ("passed",) if component == "server"
        else ("passed", "not_exposed_agent_http_health_checked")), "WORKFLOW_HTTP")
    return digest


def runtime_gate(bundle, log, now=None, replay=False):
    run_gate(bundle, complete=True)
    before, after, plan = bundle["before"], bundle["after"], bundle["plan"]
    now = now or datetime.now(timezone.utc)
    if not replay:
        fresh(after, now)
    require(0 <= (instant(after["observed_at"]) - instant(before["observed_at"])).total_seconds()
            <= 3600, "BASELINE_WINDOW")
    for evidence in (before, after):
        require(evidence["account"] == plan["account"] and evidence["region"] == plan["region"]
                and evidence["region_confirmed"] is True and evidence["cluster"] == plan["cluster"],
                "ACCOUNT_REGION_CLUSTER")
    old = {s["name"]: s for s in before["services"]}
    new = {s["name"]: s for s in after["services"]}
    require(len(old) == len(before["services"]) and len(new) == len(after["services"])
            and old.keys() == new.keys(), "SERVICE_SET_CHANGED")
    component = bundle["component"]
    name = "ipgo-dev-onebox-" + ("server" if component == "server" else "ai-api")
    cname = "server" if component == "server" else "ai-api"
    for key in old:
        a, b = old[key], new[key]
        require(a["desired"] == b["desired"] and a["deployment_configuration"] == b["deployment_configuration"]
                and a["grace"] == b["grace"], "SERVICE_CONFIG_CHANGED")
        require(b["baseline_td"] == a["td"] and b["changed_paths"] is not None, "BASELINE_NOT_COMPARED")
        allowed = {"container." + cname + ".image"} if key == name else set()
        start_change = bundle.get("approved_server_start_change")
        if start_change and component == "server" and key == name:
            setting = "IPGO_INSIGHT_DEMO_STARTS_AT"
            require(start_change.get("approval_reference") and
                    a["settings"].get(setting) == start_change["from"] and
                    b["settings"].get(setting) == start_change["to"] and
                    {k: v for k, v in a["settings"].items() if k != setting} ==
                    {k: v for k, v in b["settings"].items() if k != setting},
                    "APPROVED_START_CHANGE_MISMATCH")
            instant(start_change["to"])
            allowed.add("container.server.environment.IPGO_INSIGHT_DEMO_STARTS_AT")
        require(set(b["changed_paths"]) <= allowed,
                "UNAPPROVED_TD_CHANGE")
        if key != name:
            require(b["td"] == a["td"] and (a["desired"], a["running"], a["pending"])
                    == (b["desired"], b["running"], b["pending"]), "OTHER_SERVICE_CHANGED")
    service = new[name]
    require((service["desired"], service["running"], service["pending"]) == (1, 1, 0), "COUNTS")
    deployments = service["deployments"]
    require(len(deployments) == 1 and deployments[0] == {
        "status": "PRIMARY", "rollout": "COMPLETED", "failed": 0, "td": service["td"]}, "ROLLOUT")
    require(service["http_health_check"] is True, "APP_HEALTH_CHECK_MISSING")
    tasks = [t for t in after["tasks"] if t["service"] == name]
    require(len(tasks) == 1 and tasks[0]["td"] == service["td"]
            and tasks[0]["status"] == "RUNNING" and tasks[0]["health"] == "HEALTHY", "TASK")
    containers = [c for c in tasks[0]["containers"] if c["name"] == cname]
    digest = verified_log(log, component)
    expected_image = (plan["account"] + ".dkr.ecr." + plan["region"]
                      + ".amazonaws.com/ipgo-dev/" + component + ":"
                      + plan[component]["source_sha"] + "-arm64")
    require(len(containers) == 1 and containers[0]["image"] == expected_image
            and containers[0]["digest"] == digest and containers[0]["health"] == "HEALTHY", "APP_IDENTITY_OR_HEALTH")
    if component == "server":
        http = bundle["http_health"]
        if not replay:
            fresh(http, now)
            require(instant(http["observed_at"]) >= instant(after["observed_at"]), "HTTP_BEFORE_RUNTIME")
        require(http["http_status"] == 200 and http["body"]["status"] == "UP", "EXTERNAL_HTTP")
    return {"state": "VERIFIED_OBSERVATION", "provenance": "offline_replay" if replay else "provided_live_evidence",
            "component": component, "td": service["td"], "digest": digest,
            "next": "REVIEW_AI_DISPATCH" if component == "server" else "RECORD_RESULT",
            "external_write_performed": False, "authorization_granted": False,
            "business_e2e": "not_verified", "llm_response": "not_verified"}


def timing_report(bundle, require_full_pipeline=False):
    require(not require_full_pipeline or "phases" in bundle, "FULL_PIPELINE_PHASES_REQUIRED")
    runs = [bundle[k]["run"] for k in ("server", "ai")]
    require(instant(runs[0]["updated_at"]) <= instant(runs[1]["created_at"]), "DEPLOYMENTS_OVERLAP")
    start, end = instant(bundle["started_at"]), instant(bundle["finished_at"])
    boundaries = [start, instant(runs[0]["created_at"]), instant(runs[0]["updated_at"]),
                  instant(runs[1]["created_at"]), instant(runs[1]["updated_at"]), end]
    require(boundaries == sorted(boundaries), "TIMELINE_ORDER")
    result = {"provenance": bundle["provenance"], "seconds": {
        k: int((b - a).total_seconds()) for k, a, b in zip(
            ("preflight", "server_actions", "between_deployments", "ai_actions", "final_checks_and_record"),
            boundaries, boundaries[1:])}, "overall_seconds": int((end - start).total_seconds()),
        "business_e2e": "not_inferred", "actual_savings": "not_measured"}
    if "phases" in bundle:
        names = ["preparation", "database", "server", "ai", "client", "final_verification_and_record"]
        phases = bundle["phases"]
        require(isinstance(phases, list) and [p["name"] for p in phases] == names,
                "FULL_PIPELINE_PHASES_REQUIRED")
        cursor = start
        seconds = {}
        for phase in phases:
            begin, finish = instant(phase["started_at"]), instant(phase["finished_at"])
            require(begin == cursor and begin <= finish <= end, "PHASE_GAP_OR_OVERLAP")
            require(phase["status"] in ("success", "failed", "blocked", "skipped"), "PHASE_STATUS")
            require(phase["status"] != "skipped" or
                    (begin == finish and bool(phase.get("reason"))), "SKIPPED_PHASE_REASON")
            if phase["name"] in ("server", "ai"):
                run = bundle[phase["name"]]["run"]
                require(begin <= instant(run["created_at"]) <= instant(run["updated_at"]) <= finish,
                        "RUN_OUTSIDE_PHASE")
            seconds[phase["name"]] = (finish - begin).total_seconds()
            cursor = finish
        require(cursor == end, "UNRECORDED_FINAL_TIME")
        result["phase_seconds"] = seconds
        result["phase_statuses"] = {p["name"]: p["status"] for p in phases}
        result["full_pipeline_seconds"] = (end - start).total_seconds()
        # This measures elapsed time, not deployment authorization, business success, or savings.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run", "verify", "timing"))
    parser.add_argument("--full-pipeline", action="store_true",
                        help="timing requires preparation/DB/server/AI/client/final record coverage")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--job-log", type=Path)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    try:
        bundle = json.loads(args.bundle.read_text())
        if args.command == "preflight":
            result = baseline_gate(bundle, replay=args.replay)
        elif args.command == "run":
            result = {"state": run_gate(bundle), "authorization_granted": False,
                      "provenance": "offline_replay" if args.replay else "provided_evidence"}
        elif args.command == "verify":
            require(args.job_log is not None, "JOB_LOG_REQUIRED")
            result = runtime_gate(bundle, args.job_log.read_text(), replay=args.replay)
        else:
            result = timing_report(bundle, require_full_pipeline=args.full_pipeline)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (Blocked, KeyError, ValueError, TypeError, OSError) as exc:
        # 원문/예외 본문에 인증정보가 있을 수 있으므로 고정 코드만 표시한다.
        reason = str(exc) if isinstance(exc, Blocked) else "EVIDENCE_INVALID_OR_MISSING"
        print(json.dumps({"state": "BLOCKED", "reason": reason,
                          "authorization_granted": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

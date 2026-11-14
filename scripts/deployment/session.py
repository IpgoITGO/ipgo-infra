"""로컬 증거·시간 기록과 GitHub CI 읽기. 배포·승인 전송 없음."""
import argparse
import hashlib
import json
import os
import subprocess
import re
import shutil
import resource
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import review
import worklog


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    # New output only; never replace historical evidence or follow output symlinks.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def elapsed(start, end):
    seconds = (worklog.instant(end) - worklog.instant(start)).total_seconds()
    worklog.require(seconds >= 0, "negative interval")
    return seconds

def json_lines(output):
    return [json.loads(line) for line in output.splitlines() if line.strip()]

def close_check(directory, event_id, runner=subprocess.run):
    """라우팅 마감·알림을 같은 호출에서 처리한다. 알림 확인/ack·원장 종료는 자동 수행하지 않는다."""
    directory = Path(directory)
    started, started_at = time.perf_counter(), datetime.now(timezone.utc).isoformat()
    journal = worklog.transact(directory, lambda _: None)
    worklog.require(journal[-1].get("stage") == "finalization", "finalization stage required")
    proof = directory / "completion.json"
    if not proof.exists():
        proof = directory / "client-receipt.json"
    worklog.evidence(proof)
    worklog.require(read(proof).get("validation_passed") is True, "verified completion required")
    worklog.require(not (directory / "summary.json").exists(), "summary already exists")
    receipt_path = directory / "router-closed.json"
    worklog.require(re.fullmatch(r"[a-f0-9]{32}", event_id), "invalid event id")
    def call(args):
        response = runner(args, capture_output=True, text=True, check=True)
        return json_lines(response.stdout)
    if receipt_path.exists():
        cached = read(receipt_path)
        worklog.require(cached["event_id"] == event_id and any(
            x.get("event_id") == event_id and x.get("status") == "success" and x.get("validation") == "passed"
            for x in cached["result"]), "different or unconfirmed closing event")
    else:
        result = call(["codex-route", "desktop-finish", event_id, "--status", "success", "--validation", "passed"])
        worklog.require(any(x.get("event_id") == event_id and x.get("status") == "success"
                            and x.get("validation") == "passed" for x in result),
                        "routing close not confirmed")
        save(receipt_path, {"event_id": event_id, "result": result})
    result = call(["codex-route", "output-report", "--refresh"])
    report = next((x for x in result if "pending_notices" in x and "new_notices" in x
                   and "pending_notice_count" in x), None)
    worklog.require(report is not None, "output notice observation missing")
    worklog.require(report.get("failed_refreshes") == 0 and
                    type(report["pending_notice_count"]) is int and report["pending_notice_count"] >= 0
                    and isinstance(report["pending_notices"], list) and isinstance(report["new_notices"], list),
                    "output refresh incomplete")
    pending = bool(report["pending_notices"] or report["new_notices"] or report["pending_notice_count"])
    status = {"state": "OUTPUT_NOTICE_PENDING" if pending else "READY_TO_FINISH",
            "started_at": started_at, "checked_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": time.perf_counter() - started,
            "notices": report, "journal_closed": False, "authorization_granted": False}
    save(directory / f"close-check-{time.time_ns()}.json", status)
    return status


def merge_guard(directory, snapshot_path, plan_path):
    """판단 입력을 먼저 봉인하고 실패 조건을 보존한다. 병합·승인은 수행하지 않는다."""
    directory = Path(directory)
    worklog.evidence(snapshot_path)
    worklog.evidence(plan_path)
    snapshot, plan = read(snapshot_path), read(plan_path)
    key = str(time.time_ns())
    source = directory / f"merge-guard-{key}-input.json"
    save(source, {"at": datetime.now(timezone.utc).isoformat(), "snapshot": snapshot, "plan": plan})
    reasons = []
    if not isinstance(plan.get("author"), str) or not plan["author"]:
        reasons.append({"code": "INVALID_PLAN_AUTHOR"})
    def equal(code, actual, expected):
        if actual != expected:
            reasons.append({"code": code, "expected": expected, "observed": actual})
    equal("HEAD_CHANGED", snapshot.get("headRefOid"), plan.get("sha"))
    if not isinstance(plan.get("sha"), str) or not re.fullmatch(r"[a-f0-9]{40}", plan["sha"]):
        reasons.append({"code": "INVALID_PLAN_SHA"})
    equal("BASE_BRANCH", snapshot.get("baseRefName"), "dev")
    equal("PR_STATE", snapshot.get("state"), "OPEN")
    equal("DRAFT", snapshot.get("isDraft"), False)
    equal("MERGEABLE", snapshot.get("mergeable"), "MERGEABLE")
    equal("MERGE_STATE", snapshot.get("mergeStateStatus"), "CLEAN")
    equal("AUTHOR", (snapshot.get("author") or {}).get("login"), plan.get("author"))
    if snapshot.get("reviewDecision") not in ("", "APPROVED"):
        reasons.append({"code": "APPROVAL", "observed": snapshot.get("reviewDecision")})
    if any(x.get("state") == "CHANGES_REQUESTED" for x in snapshot.get("latestReviews", [])):
        reasons.append({"code": "CHANGES_REQUESTED"})
    threads = snapshot.get("threads", {})
    if threads.get("pageInfo", {}).get("hasNextPage") is not False or "nodes" not in threads:
        reasons.append({"code": "INCOMPLETE_REVIEW_THREADS"})
    elif any(x.get("isResolved") is not True for x in threads["nodes"]):
        reasons.append({"code": "UNRESOLVED_REVIEW"})
    checks, expected = snapshot.get("statusCheckRollup", []), plan.get("checks", [])
    if not isinstance(expected, list) or not all(isinstance(x, str) for x in expected):
        reasons.append({"code": "INVALID_PLAN_CHECKS"})
        expected = []
    if not expected or len(set(expected)) != len(expected) or len(checks) != len(expected) or {x.get("name") for x in checks} != set(expected):
        reasons.append({"code": "CHECK_SET", "expected": expected, "observed": [x.get("name") for x in checks]})
    failed = [{"name": x.get("name"), "status": x.get("status"), "conclusion": x.get("conclusion")} for x in checks
              if x.get("status") != "COMPLETED" or x.get("conclusion") != "SUCCESS"]
    if failed:
        reasons.append({"code": "CHECK_RESULT", "checks": failed})
    result = {"state": "BLOCKED" if reasons else "MERGE_GUARD_PASSED", "reasons": reasons,
              "input": worklog.evidence(source), "authorization_granted": False}
    save(directory / f"merge-guard-{key}-result.json", result)
    return result

def ci_complete(directory, plan_path, runner=subprocess.run):
    """고정된 읽기 전용 CLI로 같은 CI를 기다려 검증하고 기록 단계로 전환한다."""
    directory, plan_path = Path(directory), Path(plan_path)
    worklog.evidence(plan_path)
    plan = read(plan_path)
    plan_sha = digest(plan_path)
    repo, run_id, sha = plan["repo"], plan["run_id"], plan["sha"]
    jobs = plan["jobs"]
    worklog.require(isinstance(repo, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", repo), "invalid repository")
    worklog.require(type(run_id) is int and run_id > 0 and isinstance(sha, str)
                    and re.fullmatch(r"[a-f0-9]{40}", sha), "invalid run or SHA")
    branch = plan["branch"]
    worklog.require(isinstance(branch, str) and ((plan["event"] == "push" and branch == "dev")
                    or (plan["event"] == "pull_request" and re.fullmatch(r"feature/[A-Za-z0-9_./-]+", branch)))
                    and plan["workflow"] in (".github/workflows/test.yml", ".github/workflows/terraform-check.yml"),
                    "unsupported CI boundary")
    worklog.require(isinstance(jobs, list) and jobs and all(isinstance(j, str) and 0 < len(j) <= 120
                    and not any(ord(c) < 32 for c in j) for j in jobs) and len(set(jobs)) == len(jobs),
                    "expected jobs required")
    events = worklog.transact(directory, lambda _: None)
    stage = next(e for e in reversed(events) if e["type"] in ("start", "stage"))
    worklog.require(stage["stage"] == "validation", "validation stage required")
    output = directory / "ci-validation.json"
    worklog.require(not output.exists(), "existing CI receipt")
    started, cpu_started = time.perf_counter(), time.process_time()
    def child_cpu():
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        return usage.ru_utime + usage.ru_stime
    child_started = child_cpu()
    cli_wall = cli_python_cpu = sleep_wall = 0.0
    api_calls = 0
    def get(suffix):
        nonlocal cli_wall, cli_python_cpu, api_calls
        before, cpu_before = time.perf_counter(), time.process_time()
        api_calls += 1
        try:
            response = runner(["gh", "api", f"repos/{repo}/actions/runs/{run_id}{suffix}"],
                              capture_output=True, text=True, check=True, timeout=30)
            return json.loads(response.stdout)
        except subprocess.SubprocessError as error:
            save(directory / "ci-request-failure.json", {"error": str(error),
                 "stdout": str(getattr(error, "stdout", "") or ""),
                 "stderr": str(getattr(error, "stderr", "") or "")})
            raise
        finally:
            cli_wall += time.perf_counter() - before
            cli_python_cpu += time.process_time() - cpu_before
    # 상태만 5초 간격으로 읽는다. jobs 원본은 완료 뒤 한 번만 수집한다.
    with (directory / "ci-watch.log").open("x", encoding="utf-8") as stream:
        os.chmod(stream.name, 0o600)
        while True:
            worklog.require(time.perf_counter() - started < 1800, "CI wait deadline exceeded")
            worklog.require(digest(plan_path) == plan_sha, "CI plan changed during wait")
            run = get("")
            identity = (run["id"] == run_id and run["head_sha"] == sha and run["head_branch"] == branch
                        and run["event"] == plan["event"] and run["path"] == plan["workflow"])
            stream.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "status": run["status"],
                                     "conclusion": run["conclusion"], "identity_valid": identity}) + "\n")
            stream.flush()
            if not identity or run["status"] == "completed":
                save(directory / "ci-run.json", run)
                worklog.require(identity, "CI identity mismatch")
                break
            before = time.perf_counter()
            time.sleep(5)
            sleep_wall += time.perf_counter() - before
    observed = datetime.now(timezone.utc).isoformat()
    worklog.require(run["conclusion"] == "success", "CI failed")
    result = get("/jobs?per_page=100")
    save(directory / "ci-jobs.json", result)
    actual = result["jobs"]
    worklog.require(run["id"] == run_id and run["head_sha"] == sha and run["head_branch"] == plan["branch"]
                    and run["event"] == plan["event"] and run["path"] == plan["workflow"]
                    and run["status"] == "completed" and run["conclusion"] == "success", "CI identity or result mismatch")
    worklog.require(result["total_count"] == len(actual) == len(jobs)
                    and {j["name"] for j in actual} == set(jobs)
                    and all(j["status"] == "completed" and j["conclusion"] == "success" for j in actual),
                    "missing, extra, skipped or failed CI job")
    ended = max(worklog.instant(j["completed_at"]) for j in actual)
    worklog.require(worklog.instant(observed) >= ended, "CI observation precedes completion")
    worklog.require(digest(plan_path) == plan_sha, "CI plan changed during execution")
    wall, python_cpu = time.perf_counter() - started, time.process_time() - cpu_started
    gh_cpu = child_cpu() - child_started
    external_non_cpu = max(0.0, cli_wall - cli_python_cpu - gh_cpu)
    profile = {"wall_seconds": wall, "python_cpu_seconds": python_cpu, "gh_cpu_seconds": gh_cpu,
               "cli_wall_seconds": cli_wall, "cli_non_cpu_seconds": external_non_cpu,
               "poll_sleep_seconds": sleep_wall, "api_calls": api_calls, "poll_interval_seconds": 5,
               "other_non_cpu_seconds": max(0.0, wall - python_cpu - gh_cpu - external_non_cpu - sleep_wall),
               "limit": "CLI non-CPU includes network, process startup and scheduling; not pure network time. Remote CI CPU is unobserved."}
    save(directory / "ci-profile.json", profile)
    facts = {"state": "CI_VALIDATION_COLLECTED", "validation_passed": True, "repo": repo,
             "run_id": run_id, "sha": sha, "url": run["html_url"], "event": plan["event"],
             "ci_finished_at": ended.isoformat(), "observed_at": observed,
             "collected_at": datetime.now(timezone.utc).isoformat(), "jobs": jobs,
             "profile": profile,
             "evidence": [worklog.evidence(directory / name) for name in ("ci-run.json", "ci-jobs.json")],
             "plan_sha256": plan_sha, "human_review": "pending", "authorization_granted": False}
    save(output, facts)
    worklog.record(directory, "stage", stage="documentation", kind="work", outcome="completed", reason=None, target=None)
    return facts


def server_complete(directory, worktree, observed_at, java_exit, python_exit):
    directory, worktree = Path(directory), Path(worktree).resolve()
    worklog.require(java_exit == python_exit == 0, "local command failed")
    output = directory / "server-validation.json"
    worklog.require(not output.exists() and not (directory / "final-xml").exists(), "existing local evidence")
    source = read(directory / "final-source-hashes.json")
    worklog.require(bool(source), "missing source fingerprints")
    for name, expected in source.items():
        path = (worktree / name).resolve()
        worklog.require(path.is_relative_to(worktree) and digest(path) == expected, "source changed")
    counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    files = list((worktree / "build/test-results/test").glob("TEST-*.xml"))
    worklog.require(bool(files), "missing JUnit results")
    for path in files:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as error:
            raise ValueError("invalid JUnit XML") from error
        for key in counts:
            counts[key] += int(root.get(key, 0))
    worklog.require(counts["tests"] > counts["skipped"] and not counts["failures"] and not counts["errors"], "JUnit failed")
    jars = list((worktree / "build/libs").glob("*.jar"))
    worklog.require(bool(jars), "missing runtime JAR")
    ended = (directory / "java-finished.txt").read_text().strip()
    worklog.require(elapsed(ended, observed_at) >= 0, "invalid observation time")
    facts = {"state": "LOCAL_VALIDATION_COLLECTED", "validation_passed": True,
             "java_exit": java_exit, "python_exit": python_exit, "junit": counts,
             "java_finished_at": ended, "observed_at": observed_at,
             "collected_at": datetime.now(timezone.utc).isoformat(),
             "jar_sha256": {str(path.relative_to(worktree)): digest(path) for path in jars},
             "source_sha256": source, "human_review": "pending", "authorization_granted": False}
    shutil.copytree(worktree / "build/test-results/test", directory / "final-xml")
    save(output, facts)
    return facts


def handoff(directory, component, replay=False):
    directory = Path(directory)
    preflight = read(directory / "preflight.json")
    before = preflight["before"]
    if component == "ai":
        receipt = read(directory / "server-receipt.json")
        review.require(receipt["bundle_sha256"] == digest(directory / "server-verify.json") and
                       receipt["log_sha256"] == digest(directory / "server-job.log"), "SERVER_RECEIPT_CHANGED")
        review.require(receipt["result"]["state"] == "VERIFIED_OBSERVATION" and
                       receipt["result"]["provenance"] == ("offline_replay" if replay else "provided_live_evidence"),
                       "SERVER_VERIFICATION_REQUIRED")
        before = read(directory / "server-verify.json")["after"]
    bundle = {"component": component, "plan": preflight["plan"], "before": before}
    for key in ("dispatch", "run", "jobs", "after"):
        bundle[key] = read(directory / f"{component}-{key}.json")
    if component == "server":
        bundle["http_health"] = read(directory / "server-http.json")
        change = directory / "approved-server-start-change.json"
        if change.exists():
            bundle["approved_server_start_change"] = read(change)
    log = directory / f"{component}-job.log"
    result = review.runtime_gate(bundle, log.read_text(), replay=replay)
    output = directory / f"{component}-verify.json"
    receipt_path = directory / f"{component}-receipt.json"
    review.require(not output.exists() and not receipt_path.exists(), "HANDOFF_ALREADY_RECORDED")
    save(output, bundle)
    save(receipt_path, {"result": result, "verified_at": datetime.now(timezone.utc).isoformat(),
                        "bundle_sha256": digest(output), "log_sha256": digest(log)})
    return result


def audit(bundle, client_run):
    review.timing_report(bundle, require_full_pipeline=True)
    runs = [bundle["server"]["run"], bundle["ai"]["run"], client_run]
    review.require(len({r["id"] for r in runs}) == 3, "RUN_IDS_DUPLICATED")
    start, end = review.instant(bundle["started_at"]), review.instant(bundle["finished_at"])
    points = [start]
    for run in runs:
        review.require(run["status"] == "completed", "RUN_NOT_COMPLETE")
        points.extend([review.instant(run["created_at"]), review.instant(run["updated_at"])])
    points.append(end)
    review.require(points == sorted(points), "THREE_RUN_TIMELINE_ORDER")
    phase = next(p for p in bundle["phases"] if p["name"] == "client")
    review.require(review.instant(phase["started_at"]) <= points[5] <= points[6] <=
                   review.instant(phase["finished_at"]), "CLIENT_RUN_OUTSIDE_PHASE")
    durations = [(b - a).total_seconds() for a, b in zip(points, points[1:])]
    keys = ["before_first_app", "server_actions", "server_to_ai", "ai_actions",
            "ai_to_client", "client_actions", "after_last_app"]
    app = sum(durations[i] for i in (1, 3, 5))
    total = (end - start).total_seconds()
    return {"provenance": "audit_of_provided_records", "interval_seconds": dict(zip(keys, durations)),
            "app_actions_seconds": app, "outside_app_actions_seconds": total - app,
            "total_seconds": total, "actual_savings": "not_measured",
            "outside_time_is_not_all_safety_checks": True, "authorization_granted": False}


def markdown(result):
    def elapsed(seconds):
        seconds = round(seconds)
        return f"{seconds // 60}분 {seconds % 60:02d}초"
    names = ["첫 앱 실행 전(준비·DB 포함)", "서버 Actions", "서버→AI 사이", "AI Actions",
             "AI→프론트 사이", "프론트 Actions", "마지막 앱 완료 후 확인·기록"]
    rows = ["# 제공된 배포 기록의 시간 집계", "", "| 구간 | 시간 |", "|---|---:|"]
    rows.extend(f"| {label} | {elapsed(value)} |" for label, value in
                zip(names, result["interval_seconds"].values()))
    rows += ["", f"전체 {elapsed(result['total_seconds'])}, 앱 Actions {elapsed(result['app_actions_seconds'])}, "
             f"그 외 {elapsed(result['outside_app_actions_seconds'])}.", "",
             "앱 외 시간에는 작업·승인 대기·도구 오류 진단·조회·기록이 섞여 있다. 개별 작업의 실제 계측 없이 전부 불필요한 시간으로 단정하지 않는다.",
             "이 집계는 배포 승인·검증·실제 단축 효과를 증명하지 않는다.", ""]
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("handoff")
    check.add_argument("directory", type=Path)
    check.add_argument("component", choices=("server", "ai"))
    check.add_argument("--replay", action="store_true")
    report = sub.add_parser("audit")
    report.add_argument("bundle", type=Path)
    report.add_argument("--client-run", type=Path, required=True)
    report.add_argument("--report", type=Path)
    close = sub.add_parser("close-check")
    close.add_argument("directory", type=Path)
    close.add_argument("--event-id", required=True)
    ci = sub.add_parser("ci-complete")
    ci.add_argument("directory", type=Path)
    ci.add_argument("--plan", type=Path, required=True)
    guard = sub.add_parser("merge-guard")
    guard.add_argument("directory", type=Path)
    guard.add_argument("--snapshot", type=Path, required=True)
    guard.add_argument("--plan", type=Path, required=True)
    server = sub.add_parser("server-complete")
    server.add_argument("directory", type=Path)
    server.add_argument("--worktree", type=Path, required=True)
    server.add_argument("--observed-at", required=True)
    server.add_argument("--java-exit", type=int, required=True)
    server.add_argument("--python-exit", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "merge-guard":
            result = merge_guard(args.directory, args.snapshot, args.plan)
        elif args.command == "ci-complete":
            result = ci_complete(args.directory, args.plan)
        elif args.command == "server-complete":
            result = server_complete(args.directory, args.worktree, args.observed_at, args.java_exit, args.python_exit)
        elif args.command == "close-check":
            result = close_check(args.directory, args.event_id)
        elif args.command == "handoff":
            result = handoff(args.directory, args.component, replay=args.replay)
        else:
            result = audit(read(args.bundle), read(args.client_run))
            if args.report:
                save(args.report, markdown(result))
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result.get("state") == "BLOCKED" else 0
    except (review.Blocked, KeyError, ValueError, TypeError, OSError, subprocess.SubprocessError):
        print(json.dumps({"state": "BLOCKED", "reason": "EVIDENCE_INVALID_OR_OUTPUT_EXISTS",
                          "authorization_granted": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

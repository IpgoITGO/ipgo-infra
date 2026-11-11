"""로컬 증거 조립·단계 인계·시간 보고. 네트워크/배포/승인 전송 없음."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import review


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
    args = parser.parse_args()
    try:
        if args.command == "handoff":
            result = handoff(args.directory, args.component, replay=args.replay)
        else:
            result = audit(read(args.bundle), read(args.client_run))
            if args.report:
                save(args.report, markdown(result))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (review.Blocked, KeyError, ValueError, TypeError, OSError):
        print(json.dumps({"state": "BLOCKED", "reason": "EVIDENCE_INVALID_OR_OUTPUT_EXISTS",
                          "authorization_granted": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

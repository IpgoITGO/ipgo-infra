"""로컬 작업 시간·재검사 원장. 네트워크·배포·승인·검증 생략 기능은 없다."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

STAGES = ("preparation", "investigation", "implementation", "validation", "database", "approval",
          "deployment", "handoff", "documentation", "finalization")
KINDS = ("work", "approval_wait", "execution_wait", "rework")
OUTCOMES = ("completed", "failed", "blocked", "cancelled")
REASONS = ("initial", "source_changed", "context_changed", "stale", "mandatory_boundary",
           "previous_failure", "missing_evidence")
BOUNDARIES = ("immutable", "mutable_read", "write_guard", "post_change")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.utcoffset() is not None, "timezone required")
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def label(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:/_.@-]{0,159}", value),
            "use a short identifier, without secrets or free-form text")
    return value


def evidence(path):
    path = Path(path)
    require(path.is_absolute(), "evidence path must be absolute; do not depend on the current directory")
    require(not path.is_symlink() and path.is_file(), "evidence must be a regular non-symlink file")
    require(not path.name.startswith(".env") and not any(
        word in path.name.lower() for word in ("credential", "tfstate", "tfplan", "private-key")),
        "do not register credential or Terraform state/plan files")
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def validate(events):
    require(events and events[0]["type"] == "start", "start event required")
    first = events[0]
    require(first["version"] == 1 and first["provenance"] in ("actual", "synthetic", "replay")
            and first["coverage"] in ("full", "partial"), "invalid provenance or coverage")
    previous = instant(first["at"])
    closed = False
    for index, event in enumerate(events, 1):
        require(event["seq"] == index and not closed, "invalid sequence or event after finish")
        current = instant(event["at"])
        require(current >= previous, "clock moved backwards; preserve the original and investigate")
        require(event["type"] in ("start", "stage", "check", "skip", "finish"), "unknown event")
        require(index == 1 or event["type"] != "start", "duplicate start")
        if event["type"] in ("start", "stage"):
            require(event["stage"] in STAGES and event["kind"] in KINDS, "invalid stage/kind")
        if event["type"] == "finish":
            require(event["outcome"] in OUTCOMES, "invalid finish outcome")
            closed = True
        previous = current


def start(directory, task, provenance="actual", coverage="full", at=None):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not directory.is_symlink() and directory.stat().st_uid == os.getuid()
            and stat.S_IMODE(directory.stat().st_mode) == 0o700,
            "use a private directory with mode 0700")
    event = {"version": 1, "seq": 1, "type": "start", "at": at or now(), "task": label(task),
             "provenance": provenance, "coverage": coverage, "stage": "preparation", "kind": "work"}
    validate([event])
    fd = os.open(directory / "events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(event) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return event


def transact(directory, operation):
    path = Path(directory) / "events.jsonl"
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW)
    with os.fdopen(fd, "r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == os.getuid(), "journal must be an owned regular file with mode 0600")
        raw = stream.read()
        require(raw.endswith("\n"), "incomplete journal; do not overwrite or silently repair")
        events = [json.loads(line) for line in raw.splitlines()]
        validate(events)
        new = operation(events)
        if new is not None:
            new = {"seq": len(events) + 1, **new}
            validate(events + [new])
            stream.write(json.dumps(new, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            return new
        return events


def record(directory, event_type, at=None, **fields):
    def operation(events):
        require(events[-1]["type"] != "finish", "session already finished; use a new directory")
        event = {"type": event_type, "at": at or now(), **fields}
        if event_type == "stage":
            require(event["outcome"] in OUTCOMES, "invalid previous-stage outcome")
            require(event.get("reason") in REASONS[1:] if event["kind"] == "rework" else True,
                    "rework requires a reason")
            if event.get("target"):
                label(event["target"])
        elif event_type == "check":
            label(event["name"])
            label(event["scope"])
            require(event["action"] in ("executed", "reused") and
                    event["result"] in ("passed", "failed", "unknown") and
                    event["boundary"] in BOUNDARIES, "invalid check metadata")
            previous = [e for e in events if e["type"] == "check" and e["name"] == event["name"]]
            if event["action"] == "reused":
                require(event["boundary"] == "immutable", "fresh boundary checks cannot be reused")
                refs = [e for e in previous if e["seq"] == event.get("reference")]
                require(refs and refs[0]["boundary"] == "immutable" and
                        refs[0]["result"] == event["result"] == "passed" and
                        refs[0]["scope"] == event["scope"] and
                        refs[0].get("evidence") == event.get("evidence") and event.get("evidence"),
                        "reuse requires the same successful immutable scope and unchanged evidence")
                require(previous[-1]["scope"] == event["scope"] and previous[-1]["result"] == "passed"
                        and previous[-1]["boundary"] == "immutable"
                        and previous[-1].get("evidence") == event.get("evidence"),
                        "newer failed or changed evidence invalidates reuse")
                event["reason"] = "unchanged_evidence"
            else:
                require(event.get("reason") in (REASONS[1:] if previous else REASONS),
                        "repeated execution requires a specific recheck reason")
        elif event_type == "skip":
            label(event["target"])
            require(event["reason"] in ("unchanged", "not_requested", "not_applicable"), "invalid skip reason")
            require(event["reason"] != "unchanged" or event.get("evidence"),
                    "unchanged skip requires observed evidence")
        return event
    return transact(directory, operation)


def report(directory, at=None):
    events = transact(directory, lambda _: None)
    finished = events[-1]["type"] == "finish"
    until = events[-1]["at"] if finished else (at or now())
    require(instant(until) >= instant(events[-1]["at"]), "report cannot precede the latest event")
    boundaries = [e for e in events if e["type"] in ("start", "stage", "finish")]
    if not finished:
        boundaries.append({"at": until, "outcome": "in_progress"})
    intervals = []
    stages, kinds, targets = defaultdict(float), defaultdict(float), defaultdict(float)
    for left, right in zip(boundaries, boundaries[1:]):
        seconds = (instant(right["at"]) - instant(left["at"])).total_seconds()
        interval = {"stage": left["stage"], "kind": left["kind"], "target": left.get("target"),
                    "started_at": left["at"], "finished_at": right["at"], "seconds": seconds,
                    "outcome": right["outcome"], "reason": left.get("reason")}
        intervals.append(interval)
        stages[left["stage"]] += seconds
        kinds[left["kind"]] += seconds
        if left.get("target"):
            targets[left["target"]] += seconds
    checks = [e for e in events if e["type"] == "check"]
    counts = Counter(e["name"] for e in checks)
    total = (instant(until) - instant(events[0]["at"])).total_seconds()
    require(abs(sum(stages.values()) - total) < 0.001, "unaccounted time")
    return {"provenance": events[0]["provenance"], "coverage": events[0]["coverage"],
            "task": events[0]["task"], "started_at": events[0]["at"], "observed_until": until,
            "state": events[-1].get("outcome") if finished else "in_progress", "total_seconds": total,
            "stage_seconds": dict(stages), "kind_seconds": dict(kinds), "target_seconds": dict(targets),
            "intervals": intervals,
            "checks": checks, "repeated_check_names": {k: v for k, v in counts.items() if v > 1},
            "skipped": [e for e in events if e["type"] == "skip"],
            "authorization_granted": False, "business_success": "not_inferred",
            "actual_savings": "not_measured", "journal_event_count": len(events)}


def change(name, previous, current):
    require(previous >= 0 and current >= 0, "negative duration")
    return {"name": name, "previous_seconds": previous, "current_seconds": current,
            "reduction_seconds": previous - current,
            "reduction_percent": (previous - current) / previous * 100 if previous else None}


def timing_values(summary, run):
    require(summary["coverage"] == "full" and summary["provenance"] == "actual", "partial/synthetic scope")
    docs = [i for i in summary["intervals"] if i["stage"] == "documentation"]
    require(docs and "finalization" in summary["stage_seconds"], "record/close boundaries required")
    start, end = instant(summary["started_at"]), instant(run["updated_at"])
    boundary = instant(docs[0]["started_at"])
    require(start <= end <= boundary, "run outside measured work")
    return {"verification_observation": (boundary - end).total_seconds(),
            "documentation": summary["stage_seconds"]["documentation"],
            "finalization": summary["stage_seconds"]["finalization"]}


def timing_reference(directory, source):
    evidence(source)
    config = json.loads(Path(source).read_text())
    observation = Path(directory) / "client-observation.json"
    if not observation.exists():
        return {"state": "NOT_COMPARABLE", "reason": "NO_CLIENT_DEPLOYMENT_OBSERVATION"}
    for path in (config["summary"], config["run"], observation):
        evidence(path)
    before = json.loads(Path(config["summary"]).read_text())
    require(before["state"] == "completed", "baseline not complete")
    run = json.loads(Path(config["run"]).read_text())
    current = json.loads(observation.read_text())["run"]
    return {"state": "REFERENCE", "before": timing_values(before, run), "run": current,
            "baseline_sha256": evidence(config["summary"])["sha256"],
            "comparable": config.get("same_scope_confirmed") is True}


def timing_comparison(summary, reference):
    if reference["state"] == "NOT_COMPARABLE":
        return reference
    try:
        values = timing_values(summary, reference["run"])
    except ValueError:
        return {"state": "NOT_COMPARABLE", "reason": "CURRENT_SCOPE_OR_BOUNDARY_DIFFERS"}
    rows = [change(k, reference["before"][k], v) for k, v in values.items()]
    if not reference["comparable"]:
        for row in rows:
            row["reduction_percent"] = None
    return {"state": "OBSERVED_PAIR" if reference["comparable"] else "REFERENCE_ONLY", "rows": rows,
            "baseline_sha256": reference["baseline_sha256"], "causal_savings_proven": False}


def save_report(directory, output, outcome=None, compare=None):
    """출력 경로를 먼저 확보한다. 충돌 시 원장도 닫지 않으며 과거 보고서는 보존한다."""
    output = Path(output)
    require(output.is_absolute(), "report path must be absolute")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        try:
            reference = timing_reference(directory, compare) if compare else None
            if reference:
                timing_comparison(report(directory), reference)  # Validate before recording finish.
            if outcome is not None:
                record(directory, "finish", outcome=outcome)
            result = report(directory)
            if reference:
                result["timing_comparison"] = timing_comparison(result, reference)
        except Exception:
            # 이 호출이 만든 빈 파일만 제거한다. 원장·기존 보고서는 수정하지 않는다.
            if output.lstat().st_ino == os.fstat(stream.fileno()).st_ino:
                output.unlink()
            raise
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    return {"report": str(output), **{key: result[key] for key in (
        "state", "coverage", "total_seconds", "stage_seconds", "kind_seconds",
        "target_seconds", "repeated_check_names", "timing_comparison") if key in result}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("start")
    init.add_argument("directory", type=Path)
    init.add_argument("--task", required=True)
    init.add_argument("--provenance", choices=("actual", "synthetic", "replay"), default="actual")
    init.add_argument("--coverage", choices=("full", "partial"), default="full")
    stage = sub.add_parser("stage")
    stage.add_argument("directory", type=Path)
    stage.add_argument("stage", choices=STAGES)
    stage.add_argument("--kind", choices=KINDS, default="work")
    stage.add_argument("--outcome", choices=OUTCOMES, default="completed", help="직전 구간의 종료 상태")
    stage.add_argument("--reason", choices=REASONS[1:])
    stage.add_argument("--target", type=label)
    check = sub.add_parser("check")
    check.add_argument("directory", type=Path)
    check.add_argument("--name", required=True, type=label)
    check.add_argument("--scope", required=True, type=label)
    check.add_argument("--action", choices=("executed", "reused"), default="executed")
    check.add_argument("--result", choices=("passed", "failed", "unknown"), required=True)
    check.add_argument("--reason", choices=REASONS)
    check.add_argument("--boundary", choices=BOUNDARIES, required=True)
    check.add_argument("--evidence", type=Path)
    check.add_argument("--reference", type=int)
    skip = sub.add_parser("skip")
    skip.add_argument("directory", type=Path)
    skip.add_argument("target", type=label)
    skip.add_argument("--reason", choices=("unchanged", "not_requested", "not_applicable"), required=True)
    skip.add_argument("--evidence", type=Path)
    finish = sub.add_parser("finish")
    finish.add_argument("directory", type=Path)
    finish.add_argument("--outcome", choices=OUTCOMES, required=True)
    finish.add_argument("--out", type=Path, help="원장을 닫고 단일 보고서를 저장할 절대 경로")
    finish.add_argument("--compare", type=Path, help="검증/기록/마감 비교 기준 JSON의 절대 경로")
    summary = sub.add_parser("report")
    summary.add_argument("directory", type=Path)
    summary.add_argument("--out", type=Path)
    args = vars(parser.parse_args())
    command, directory = args.pop("command"), args.pop("directory")
    try:
        if command == "start":
            result = start(directory, **args)
        elif command == "report":
            result = save_report(directory, args["out"]) if args["out"] else report(directory)
        elif command == "finish":
            require(not args["compare"] or args["out"], "comparison requires an output report")
            result = (save_report(directory, args["out"], outcome=args["outcome"], compare=args["compare"]) if args["out"]
                      else record(directory, command, outcome=args["outcome"]))
        else:
            if args.get("evidence"):
                args["evidence"] = evidence(args["evidence"])
            result = record(directory, command, **args)
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"기록 실패: {exc}\n")


if __name__ == "__main__":
    main()

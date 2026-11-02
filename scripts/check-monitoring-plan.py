#!/usr/bin/env python3
"""Reject any change outside the approved, non-disruptive monitoring transition."""
import json
import sys

ALARMS = {
    "server-unavailable", "api-errors", "alb-errors", "database-memory-low",
    "database-storage-low", "server-cpu-high", "server-memory-high",
    "ai_api-cpu-high", "ai_api-memory-high",
}
CREATES = {
    "module.monitoring[0].aws_sns_topic.alerts",
    "module.monitoring[0].aws_sns_topic_policy.alerts",
    "module.monitoring[0].aws_sns_topic_subscription.email",
    "module.monitoring[0].aws_budgets_budget.monthly",
} | {f'module.monitoring[0].aws_cloudwatch_metric_alarm.health["{name}"]' for name in ALARMS}


def validate(plan):
    for resource in plan.get("resource_changes", []):
        change = resource["change"]
        actions = change["actions"]
        if actions == ["no-op"] or (resource.get("mode") == "data" and actions == ["read"]):
            continue
        address = resource["address"]
        if address in CREATES and actions == ["create"]:
            continue
        if address == "module.compute.aws_ecs_cluster.this" and actions == ["update"]:
            before, after = change["before"], change["after"]
            changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
            expected = [{"name": "containerInsights", "value": "disabled"}]
            if changed == {"setting"} and after.get("setting") == expected:
                continue
        raise ValueError(f"Unapproved monitoring change: {address} ({','.join(actions)})")


if __name__ == "__main__":
    try:
        validate(json.load(sys.stdin))
    except (KeyError, ValueError, TypeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    print("Monitoring-only scope verified: services, tasks, database and listeners unchanged.")

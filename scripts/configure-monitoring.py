#!/usr/bin/env python3
"""Validate Actions monitoring inputs without printing the private destination."""
import math
import os
import re
import sys


def settings(env):
    enabled = env.get("DEV_MONITORING_ENABLED", "") or "false"
    if enabled not in {"true", "false"}:
        raise ValueError("AWS_ENABLE_DEV_MONITORING must be true, false, or unset.")
    mode = env.get("CONTAINER_INSIGHTS", "") or "disabled"
    if mode not in {"disabled", "enabled", "enhanced"}:
        raise ValueError("AWS_CONTAINER_INSIGHTS must be disabled, enabled, or enhanced.")
    result = {"TF_VAR_enable_dev_monitoring": enabled, "TF_VAR_container_insights": mode}
    if enabled == "true":
        email = env.get("ALERT_EMAIL", "")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            if env.get("GITHUB_ACTOR") == "dependabot[bot]":
                raise ValueError("Dependabot cannot read Actions AWS_ALERT_EMAIL. Use the reviewed lockfile-only manual plan from an allowed dev/feature workflow; do not disable monitoring or substitute an email.")
            raise ValueError("Set the private AWS_ALERT_EMAIL secret before enabling monitoring.")
        budget = env.get("MONTHLY_BUDGET_USD", "") or "50"
        try:
            amount = float(budget)
        except ValueError:
            raise ValueError("AWS_MONTHLY_BUDGET_USD must be a positive finite number.") from None
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("AWS_MONTHLY_BUDGET_USD must be a positive finite number.")
        result.update(TF_VAR_alert_email=email, TF_VAR_monthly_budget_usd=str(amount))
    return result


if __name__ == "__main__":
    try:
        values = settings(os.environ)
    except ValueError as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")
    print("Monitoring inputs validated; destination is not published.")

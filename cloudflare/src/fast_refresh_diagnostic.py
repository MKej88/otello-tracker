"""Conservative, redacted assessment of the latest Cloudflare fast refresh.

Raw provider messages and D1 metadata can contain URLs and sensitive information.
Only allowlisted step identifiers, result states and exception class names are
included in GitHub Actions output. Unknown partial failures stay critical.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_AGE = timedelta(minutes=100)
NON_CRITICAL_STEPS = frozenset({
    "dashboard_hot_snapshot",
    "investor_snapshots",
    "brazil_snapshot",
})
_SAFE_CODE = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")


def safe_code(value: Any) -> str:
    """Allow only short code-like values in publicly readable workflow logs."""
    string = str(value or "")
    return string if _SAFE_CODE.fullmatch(string) else "unknown"


def _metadata(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def assess_fast_refresh(record: dict, *, now: datetime | None = None) -> dict:
    """Return OK, WARNING or FAILURE, with redacted step diagnostics."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    status = str(record.get("status") or "").upper()
    timestamp = record.get("finished_at") or record.get("started_at")
    if not timestamp:
        return {"severity": "FAILURE", "status": status, "age_minutes": None,
                "steps": [], "reason": "missing_timestamp"}
    try:
        last = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if last.tzinfo is None:
            raise ValueError("timezone missing")
        age = now.astimezone(UTC) - last.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return {"severity": "FAILURE", "status": status, "age_minutes": None,
                "steps": [], "reason": "invalid_timestamp"}

    age_minutes = int(age.total_seconds() // 60)
    result = {"severity": "FAILURE", "status": status,
              "age_minutes": age_minutes, "steps": [], "reason": "unhealthy_status"}
    if not timedelta(0) <= age <= MAX_AGE:
        result["reason"] = "stale_or_future_refresh"
        return result

    metadata = _metadata(record.get("metadata_json"))
    errors = metadata.get("source_errors")
    if status == "SUCCESS":
        if isinstance(errors, list) and errors:
            result["reason"] = "success_with_source_errors"
            return result
        result.update(severity="OK", reason="healthy")
        return result

    if status != "PARTIAL":
        return result

    if not isinstance(errors, list) or not errors:
        result["reason"] = "partial_without_error_details"
        return result

    step_results = metadata.get("steps")
    if not isinstance(step_results, dict):
        step_results = {}
    allow_warning = True
    for error in errors:
        if not isinstance(error, dict):
            result["steps"].append({"step": "unknown", "type": "unknown",
                                    "status": "unknown"})
            allow_warning = False
            continue
        step = safe_code(error.get("step"))
        step_result = step_results.get(step)
        if not isinstance(step_result, dict):
            step_result = {}
        result["steps"].append({
            "step": step,
            "type": safe_code(error.get("error_type")),
            "status": safe_code(step_result.get("status")),
        })
        if not (step in NON_CRITICAL_STEPS
                and step_result.get("non_critical") is True):
            allow_warning = False

    nav = step_results.get("dirty_nav")
    if not isinstance(nav, dict) or nav.get("status") != "ok":
        allow_warning = False
    if allow_warning:
        result.update(severity="WARNING", reason="confirmed_noncritical_steps")
    else:
        result["reason"] = "critical_or_unclassified_partial"
    return result

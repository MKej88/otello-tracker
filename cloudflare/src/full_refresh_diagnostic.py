"""Conservative bounded grace for an explicitly manual Cloudflare full refresh.

Only the latest RUNNING D1 job can use it, and only if the immediately previous
completed job for the same target was successful. Independent source/NAV checks
are never bypassed.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta

from nightly_trigger import nightly_due_at

MANUAL_GRACE = timedelta(minutes=15)
PREVIOUS_SUCCESS_MAX_AGE = timedelta(hours=36)
NIGHTLY_WINDOW = timedelta(minutes=55)
NIGHTLY_EARLY_TOLERANCE = timedelta(minutes=5)


def _metadata(job: dict) -> dict:
    try:
        data = json.loads(job.get("metadata_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def is_explicit_manual(job: dict) -> bool:
    trigger = str(_metadata(job).get("trigger") or "")
    return trigger in {"github_actions_manual_repair", "workflow_manual"} or trigger.startswith(
        ("workflow_dispatch:", "github_actions_manual:", "manual:")
    )


def refresh_kind(job: dict) -> str:
    """Distinguish scheduled, explicit manual, and historical ambiguous runs."""
    trigger = str(_metadata(job).get("trigger") or "")
    if trigger.startswith(("worker_cron:", "workflow_schedule:")):
        return "scheduled"
    if is_explicit_manual(job):
        return "manual"
    # Older finish_job metadata dropped the start trigger. Do not count a
    # historical *off-schedule* completed rerun as a duplicated nightly. Its
    # provenance is ambiguous and is reported separately as a warning.
    started = _time(job.get("started_at"))
    if started is None:
        return "unknown"
    delta = started - nightly_due_at(started)
    if -NIGHTLY_EARLY_TOLERANCE <= delta <= NIGHTLY_WINDOW:
        return "legacy_nightly_window"
    return "legacy_outside_window"


def plausible_legacy_recovery(job: dict, *, now: datetime, target_date: str) -> bool:
    """Off-schedule historical successes are not automatically harmless.

    When the trigger was dropped by older finish_job versions, only a run
    *after* the expected nightly due for its target date, but outside the
    scheduled window, may represent a manual recovery. Unknown/future/early
    runs never qualify. Independent duplicates are assessed by the caller.
    """
    if refresh_kind(job) != "legacy_outside_window" or job.get("status") != "SUCCESS":
        return False
    try:
        target = date.fromisoformat(target_date)
    except (TypeError, ValueError):
        return False
    if _metadata(job).get("target_date") != target.isoformat():
        return False
    started = _time(job.get("started_at"))
    finished = _time(job.get("finished_at"))
    if started is None or finished is None:
        return False
    due = datetime.combine(target + timedelta(days=1), time(3, 35), tzinfo=UTC)
    current = now.astimezone(UTC)
    return (
        due + NIGHTLY_WINDOW < started <= due + timedelta(hours=24)
        and started <= finished <= current
    )



def manual_refresh_grace(
    rows: list[dict], *, now: datetime, expected_target: str
) -> dict:
    """Return a validated previous completed SUCCESS, or fail closed."""
    result = {"under_grace": False, "previous": None, "reason": "not_manual_running",
              "age_minutes": None}
    if len(rows) < 2:
        return result
    latest, previous = rows[0], rows[1]
    if latest.get("status") != "RUNNING" or not is_explicit_manual(latest):
        return result
    if _metadata(latest).get("target_date") != expected_target:
        return {**result, "reason": "target_mismatch"}
    if latest.get("finished_at"):
        return {**result, "reason": "running_has_finish"}
    started = _time(latest.get("started_at"))
    now = now.astimezone(UTC)
    if started is None or not timedelta(0) <= now - started <= MANUAL_GRACE:
        return {**result, "reason": "outside_grace"}
    if previous.get("status") != "SUCCESS" or previous.get("error_message"):
        return {**result, "reason": "previous_not_success"}
    if _metadata(previous).get("target_date") != expected_target:
        return {**result, "reason": "previous_target_mismatch"}
    completed = _time(previous.get("finished_at"))
    if (
        completed is None or completed > started
        or not timedelta(0) <= now - completed <= PREVIOUS_SUCCESS_MAX_AGE
    ):
        return {**result, "reason": "previous_not_recent"}
    return {
        "under_grace": True, "previous": previous, "reason": "recent_manual_running",
        "age_minutes": int((now - started).total_seconds() // 60),
    }

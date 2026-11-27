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
RUNNING_GRACE = timedelta(minutes=10)  # 8 minutes at incident #869; warn first, fail if stuck.
NON_CRITICAL_STEPS = frozenset({
    "dashboard_hot_snapshot",
    "investor_snapshots",
    "brazil_snapshot",
    "bemobi_translation",
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


def assess_fast_refresh(record: dict, *, now: datetime | None = None,
                        max_age: timedelta = MAX_AGE) -> dict:
    """Return OK, WARNING or FAILURE, with redacted step diagnostics."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    status = safe_code(str(record.get("status") or "").upper())
    if status in {"SUCCESS", "PARTIAL"} and not record.get("finished_at"):
        return {"severity": "FAILURE", "status": status, "age_minutes": None,
                "steps": [], "reason": "missing_completion_timestamp"}
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
    if not timedelta(0) <= age <= max_age:
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


def assess_fast_refresh_window(records: list[dict], *,
                               now: datetime | None = None,
                               max_age: timedelta = MAX_AGE) -> dict:
    """Check latest and previous completed runs without hiding a stuck RUNNING job.

    A current RUNNING row is temporarily a warning only when it is recent and
    the immediately preceding *completed* job is independently healthy/fresh.
    UNKNOWN, FAILED, stale, missing metadata, or overlong RUNNING remains fatal.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not records:
        return {"severity": "FAILURE", "status": "MISSING", "age_minutes": None,
                "steps": [], "reason": "missing_fast_jobs"}

    latest = records[0]
    if str(latest.get("status") or "").upper() != "RUNNING":
        return assess_fast_refresh(latest, now=now, max_age=max_age)

    report = {"severity": "FAILURE", "status": "RUNNING",
              "age_minutes": None, "steps": [],
              "reason": "running_without_healthy_previous",
              "previous_status": "MISSING", "previous_age_minutes": None}
    if latest.get("finished_at"):
        report["reason"] = "running_with_completion_timestamp"
        return report
    started_at = latest.get("started_at")
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        if start.tzinfo is None:
            raise ValueError("timezone missing")
        elapsed = now.astimezone(UTC) - start.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        report["reason"] = "invalid_running_timestamp"
        return report
    report["age_minutes"] = int(elapsed.total_seconds() // 60)
    if elapsed < timedelta(0):
        report["reason"] = "future_running_timestamp"
        return report
    if elapsed >= RUNNING_GRACE:
        report["reason"] = "running_exceeded_grace"
        return report

    # Never skip a FAILED completed job to find an older successful job.
    previous = next(
        (row for row in records[1:]
         if str(row.get("status") or "").upper() != "RUNNING"), None
    )
    if previous is None:
        return report
    previous_result = assess_fast_refresh(previous, now=now, max_age=max_age)
    report["previous_status"] = previous_result["status"]
    report["previous_age_minutes"] = previous_result["age_minutes"]
    if previous_result["severity"] != "OK":
        report["reason"] = "previous_completed_unhealthy"
        return report
    report.update(severity="WARNING", reason="recent_running_with_healthy_previous")
    return report


# Only fixed categories and counts leave D1; never expose document URLs or error text.
TRANSLATION_ERROR_GROUPS_SQL = """
SELECT CASE
    WHEN translation_error LIKE 'value_validation:%' OR translation_error LIKE 'verdikontroll feilet%' THEN 'value_validation'
    WHEN translation_error LIKE '%originaldokument HTTP %' THEN 'document_http'
    WHEN translation_error LIKE '%krever OCR%' THEN 'pdf_without_text'
    WHEN translation_error LIKE 'download:%' THEN 'document_download'
    WHEN translation_error LIKE 'pdf_extraction:%' THEN 'pdf_extraction'
    WHEN translation_error LIKE 'translation:%' THEN 'ai_translation'
    WHEN translation_error LIKE 'summary:%' THEN 'ai_summary'
    WHEN translation_error LIKE 'archive:%' THEN 'archive'
    WHEN translation_error LIKE '%model%not found%' OR translation_error LIKE '%model%deprecated%'
         OR translation_error LIKE '%model%does not exist%' OR translation_error LIKE '%model%not available%' THEN 'ai_model'
    WHEN translation_error LIKE '%JsException%' OR translation_error LIKE '%PyProxy%' THEN 'runtime_binding'
    WHEN translation_error LIKE '%Workers AI%' OR translation_error LIKE '%JSON%' THEN 'ai_response'
    WHEN translation_error LIKE '%Maksimalt antall behandlingsforsøk%' THEN 'interrupted_exhausted'
    ELSE 'other'
END AS reason,
COUNT(*) AS document_count,
SUM(CASE WHEN translation_attempts >= 3 THEN 1 ELSE 0 END) AS exhausted_count
FROM source_documents sd JOIN sources s ON s.id=sd.source_id
WHERE s.code IN ('CVM','BEMOBI_IR')
  AND sd.translation_status IN ('FAILED','PENDING') AND sd.translation_error IS NOT NULL
GROUP BY 1 ORDER BY 1
"""


def public_fast_refresh_warning(record: dict, *, now: datetime, max_age: timedelta) -> dict | None:
    """Only confirmed secondary failures may narrow the public impact description."""
    report = assess_fast_refresh(record, now=now, max_age=max_age)
    if report["reason"] != "confirmed_noncritical_steps":
        return None
    steps = sorted({item["step"] for item in report["steps"]})
    payload: dict[str, Any] = {"steps": steps}
    if "bemobi_translation" in steps:
        translation = _metadata(record.get("metadata_json"))["steps"]["bemobi_translation"]
        queue = translation.get("queue")
        if isinstance(queue, dict):
            counts = {key: queue[key] for key in ("failed", "exhausted", "overdue")
                      if type(queue.get(key)) is int and queue[key] >= 0}
            failed = translation.get("failed")
            if type(failed) is int and failed >= 0:
                counts["failed_this_run"] = failed
            payload["translation_queue"] = counts
    return payload

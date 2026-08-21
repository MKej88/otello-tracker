from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

try:
    from .fx_freshness import expected_norges_bank_date, norges_bank_fx_coverage
except ImportError:
    from fx_freshness import expected_norges_bank_date, norges_bank_fx_coverage

FULL_JOB = "cloudflare_full_refresh"
FAST_JOB = "cloudflare_fast_refresh"
FAST_MAX_AGE = timedelta(minutes=90)
FULL_MAX_AGE = timedelta(hours=36)
FAST_RUNNING_MAX_AGE = timedelta(minutes=90)
FULL_RUNNING_MAX_AGE = timedelta(hours=4)


def _metadata(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    raw = row.get("metadata_json")
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _job_freshness(
    row: dict[str, Any] | None,
    *,
    now: datetime,
    completed_max_age: timedelta,
    running_max_age: timedelta,
) -> dict[str, Any]:
    if not row:
        return {"stale": True, "age_minutes": None, "reason": "missing"}

    status = str(row.get("status") or "MISSING").upper()
    timestamp = _parse_timestamp(
        row.get("started_at") if status == "RUNNING" else row.get("finished_at") or row.get("started_at")
    )
    if timestamp is None:
        return {"stale": True, "age_minutes": None, "reason": "missing_timestamp"}

    age = max(timedelta(0), now - timestamp)
    limit = running_max_age if status == "RUNNING" else completed_max_age
    stale = age > limit
    return {
        "stale": stale,
        "age_minutes": int(age.total_seconds() // 60),
        "reason": "running_too_long" if stale and status == "RUNNING" else "too_old" if stale else None,
    }


def _job_payload(
    row: dict[str, Any] | None,
    *,
    now: datetime,
    completed_max_age: timedelta,
    running_max_age: timedelta,
) -> dict[str, Any]:
    freshness = _job_freshness(
        row,
        now=now,
        completed_max_age=completed_max_age,
        running_max_age=running_max_age,
    )
    if not row:
        return {
            "available": False,
            "status": "MISSING",
            "started_at": None,
            "finished_at": None,
            "records_written": 0,
            "error_message": None,
            "has_error": False,
            "target_date": None,
            **freshness,
        }
    metadata = _metadata(row)
    return {
        "available": True,
        "status": row.get("status"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "records_written": int(row.get("records_written") or 0),
        # Keep arbitrary upstream exception text out of the public API. Detailed errors remain
        # available through the authenticated GitHub/Cloudflare diagnostics workflow.
        "error_message": None,
        "has_error": bool(row.get("error_message")),
        "target_date": metadata.get("target_date"),
        **freshness,
    }


async def _latest_job(repository, job_name: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT id, job_name, started_at, finished_at, status,
               records_written, error_message, metadata_json
        FROM job_runs
        WHERE job_name=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (job_name,),
    )


async def _latest_norges_bank_health(repository) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT sh.checked_at, sh.status, sh.error_message, sh.metadata_json
        FROM source_health sh
        JOIN sources s ON s.id=sh.source_id
        WHERE s.code='NORGES_BANK'
        ORDER BY sh.id DESC
        LIMIT 1
        """
    )


async def runtime_status_summary(
    repository,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    full_row = await _latest_job(repository, FULL_JOB)
    fast_row = await _latest_job(repository, FAST_JOB)
    norges_bank_health = await _latest_norges_bank_health(repository)
    fx = await norges_bank_fx_coverage(repository)

    full = _job_payload(
        full_row,
        now=current,
        completed_max_age=FULL_MAX_AGE,
        running_max_age=FULL_RUNNING_MAX_AGE,
    )
    fast = _job_payload(
        fast_row,
        now=current,
        completed_max_age=FAST_MAX_AGE,
        running_max_age=FAST_RUNNING_MAX_AGE,
    )
    expected_fx_date = expected_norges_bank_date(current)
    latest_common_date = fx.get("latest_common_date")
    fx_current = latest_common_date is not None and str(latest_common_date) >= expected_fx_date

    health_status = str((norges_bank_health or {}).get("status") or "MISSING").upper()
    full_status = str(full.get("status") or "MISSING").upper()
    fast_status = str(fast.get("status") or "MISSING").upper()

    ready = bool(full.get("available") and fast.get("available") and latest_common_date)
    if not ready:
        status = "DOWN"
    elif (
        not fx_current
        or bool(full.get("stale"))
        or bool(fast.get("stale"))
        or full_status in {"FAILED", "PARTIAL"}
        or fast_status in {"FAILED", "PARTIAL"}
        or health_status in {"DOWN", "DEGRADED"}
    ):
        status = "DEGRADED"
    else:
        status = "OK"

    return {
        "ready": ready,
        "status": status,
        "checked_at": current.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "full_refresh": full,
        "fast_refresh": fast,
        "norges_bank": {
            "status": health_status,
            "checked_at": (norges_bank_health or {}).get("checked_at"),
            "error_message": None,
            "has_error": bool((norges_bank_health or {}).get("error_message")),
        },
        "fx": {
            **fx,
            "expected_date": expected_fx_date,
            "current": fx_current,
        },
    }

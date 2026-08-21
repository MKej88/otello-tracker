from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

try:
    from .fx_freshness import expected_norges_bank_date, norges_bank_fx_coverage
except ImportError:
    from fx_freshness import expected_norges_bank_date, norges_bank_fx_coverage

FULL_JOB = "cloudflare_full_refresh"
FAST_JOB = "cloudflare_fast_refresh"


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


def _job_payload(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "available": False,
            "status": "MISSING",
            "started_at": None,
            "finished_at": None,
            "records_written": 0,
            "error_message": None,
            "target_date": None,
        }
    metadata = _metadata(row)
    return {
        "available": True,
        "status": row.get("status"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "records_written": int(row.get("records_written") or 0),
        "error_message": row.get("error_message"),
        "target_date": metadata.get("target_date"),
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
    current = now or datetime.now(UTC)
    full_row = await _latest_job(repository, FULL_JOB)
    fast_row = await _latest_job(repository, FAST_JOB)
    norges_bank_health = await _latest_norges_bank_health(repository)
    fx = await norges_bank_fx_coverage(repository)

    full = _job_payload(full_row)
    fast = _job_payload(fast_row)
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
            "error_message": (norges_bank_health or {}).get("error_message"),
        },
        "fx": {
            **fx,
            "expected_date": expected_fx_date,
            "current": fx_current,
        },
    }

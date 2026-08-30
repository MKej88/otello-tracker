from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

try:
    from .dashboard_hot_snapshot import dashboard_hot_snapshot_status
    from .fx_freshness import expected_norges_bank_date, norges_bank_fx_coverage
except ImportError:
    from dashboard_hot_snapshot import dashboard_hot_snapshot_status
    from fx_freshness import expected_norges_bank_date, norges_bank_fx_coverage

FULL_JOB = "cloudflare_full_refresh"
FAST_JOB = "cloudflare_fast_refresh"
WRITER_LOCK_KEY = "cloudflare_refresh_writer_lock"
FAST_MAX_AGE = timedelta(minutes=90)
FULL_MAX_AGE = timedelta(hours=36)
FAST_RUNNING_MAX_AGE = timedelta(minutes=90)
FULL_RUNNING_MAX_AGE = timedelta(hours=4)
PUBLIC_SOURCE_CODES = (
    "NORGES_BANK",
    "YAHOO_FINANCE",
    "B3",
    "CVM",
    "BEMOBI_IR",
    "NEWSWEB",
    "EURONEXT",
)


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


def _active_writer_owner(lock_row: dict[str, Any] | None, *, now: datetime) -> str | None:
    if not lock_row or not lock_row.get("value"):
        return None
    token = str(lock_row["value"])
    owner, separator, expires_text = token.rpartition("|")
    if not separator or not owner:
        return None
    expires_at = _parse_timestamp(expires_text)
    if expires_at is None or expires_at <= now:
        return None
    return owner


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


def _public_preflight_warnings(
    preflight: dict[str, Any],
    *,
    target_date: Any = None,
) -> list[dict[str, str]]:
    """Expose only curated, non-sensitive explanations for known preflight warnings."""
    raw_warnings = preflight.get("warnings")
    if not isinstance(raw_warnings, list):
        return []

    target_year = str(target_date or "")[:4]
    public_warnings: list[dict[str, str]] = []
    for warning in raw_warnings:
        if not isinstance(warning, dict):
            continue
        code = str(warning.get("name") or "").strip()
        details = warning.get("details")
        safe_details = details if isinstance(details, dict) else {}

        if code == "bemobi_cvm_current_year":
            period = f" for {target_year}" if target_year.isdigit() and len(target_year) == 4 else ""
            message = f"Bemobi / CVM: Ingen CVM-dokumenter funnet{period}."
        elif code == "dashboard_quality":
            data_status = str(safe_details.get("data_status") or "").upper()
            if data_status == "ESTIMATED":
                message = "Dashboardkvalitet: NAV bruker estimerte data mellom rapportdatoer."
            elif data_status == "DEGRADED":
                message = "Dashboardkvalitet: Datakvaliteten er redusert og bør kontrolleres."
            else:
                message = "Dashboardkvalitet: Nattkontrollen registrerte en kvalitetsadvarsel."
        elif code == "buyback_forecast_current_state":
            message = "Tilbakekjøpsprognose: Prognosemotoren er ikke klar i gjeldende tilstand."
        else:
            # Unknown checks may contain arbitrary upstream details. Keep those private.
            continue

        public_warnings.append({"code": code, "message": message})

    return public_warnings


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
    raw_source_health = metadata.get("source_health")
    source_health = raw_source_health if isinstance(raw_source_health, dict) else {}
    raw_preflight = metadata.get("preflight")
    preflight = raw_preflight if isinstance(raw_preflight, dict) else {}
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
        "source_health": {
            code: str(source_health[code]).upper()
            for code in PUBLIC_SOURCE_CODES
            if code in source_health
        },
        "preflight": {
            "ready": bool(preflight.get("ready")),
            "blocker_count": len(preflight.get("blockers") or []),
            "warning_count": len(preflight.get("warnings") or []),
            "warnings": _public_preflight_warnings(
                preflight,
                target_date=metadata.get("target_date"),
            ),
        }
        if preflight
        else None,
        **freshness,
    }


def _guard_orphaned_full_job(
    payload: dict[str, Any],
    row: dict[str, Any] | None,
    lock_row: dict[str, Any] | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Do not expose RUNNING when its full-refresh writer lease is gone or expired."""
    if not row or str(row.get("status") or "").upper() != "RUNNING":
        return payload
    target_date = str(payload.get("target_date") or "").strip()
    owner = _active_writer_owner(lock_row, now=now)
    if target_date and owner and owner.startswith(f"full:{target_date}:"):
        return payload
    return {
        **payload,
        "status": "FAILED",
        "stale": True,
        "reason": "writer_lease_inactive",
        "has_error": True,
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


async def _writer_lock(repository) -> dict[str, Any] | None:
    return await repository.first(
        "SELECT value, updated_at FROM runtime_state WHERE key=? LIMIT 1",
        (WRITER_LOCK_KEY,),
    )


async def runtime_status_summary(
    repository,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    full_row = await _latest_job(repository, FULL_JOB)
    fast_row = await _latest_job(repository, FAST_JOB)
    writer_lock = await _writer_lock(repository)
    norges_bank_health = await _latest_norges_bank_health(repository)
    fx = await norges_bank_fx_coverage(repository)
    hot_snapshot = await dashboard_hot_snapshot_status(repository, now=current)

    full = _job_payload(
        full_row,
        now=current,
        completed_max_age=FULL_MAX_AGE,
        running_max_age=FULL_RUNNING_MAX_AGE,
    )
    full = _guard_orphaned_full_job(full, full_row, writer_lock, now=current)
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
        "hot_snapshot": hot_snapshot,
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

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
FULL_NAV_CALCULATION_VERSION = "full-market-nav-daily-v2"
CORE_NAV_CALCULATION_VERSION = "core-market-nav-daily-v1"
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


def _json_object(raw: Any) -> dict[str, Any]:
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


def _active_writer_owner(
    lock_row: dict[str, Any] | None, *, now: datetime
) -> str | None:
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
        row.get("started_at")
        if status == "RUNNING"
        else row.get("finished_at") or row.get("started_at")
    )
    if timestamp is None:
        return {"stale": True, "age_minutes": None, "reason": "missing_timestamp"}

    age = max(timedelta(0), now - timestamp)
    limit = running_max_age if status == "RUNNING" else completed_max_age
    stale = age > limit
    return {
        "stale": stale,
        "age_minutes": int(age.total_seconds() // 60),
        "reason": (
            "running_too_long"
            if stale and status == "RUNNING"
            else "too_old" if stale else None
        ),
    }


def _expected_between_reports(details: dict[str, Any]) -> bool:
    """Return True when lower-quality flags only describe normal between-report estimates."""
    data_status = str(details.get("data_status") or "").upper()
    cash_quality = str(details.get("cash_quality") or "").upper()
    cash_calibration_quality = str(details.get("cash_calibration_quality") or "").upper()
    share_count_quality = str(details.get("share_count_quality") or "").upper()
    ona_quality = str(details.get("ona_quality") or "").upper()
    receivable_quality = str(details.get("receivable_quality") or "").upper()
    option_quality = str(details.get("option_quality") or "").upper()
    notes = str(details.get("quality_notes") or "").lower()

    if data_status == "ESTIMATED":
        return True
    if data_status != "DEGRADED":
        return False

    actionable = (
        cash_calibration_quality == "HIGH_RESIDUAL"
        or receivable_quality == "ESTIMATED_GROSS"
        or "gross-estimated" in notes
    )
    expected_markers = (
        cash_quality in {"FORECAST_PARTIAL", "ANCHORED_ESTIMATE"}
        or share_count_quality == "POTENTIALLY_STALE"
        or ona_quality in {"FORECAST_PARTIAL", "INTERPOLATED"}
        or "partial forecast data" in notes
        or "interpolated between reported anchors" in notes
        or option_quality in {"INTERPOLATED_TO_REPORTED", "FORECAST_MARK_TO_MARKET"}
        or "latest reported risk-free-rate/volatility" in notes
    )
    return expected_markers and not actionable


def _dashboard_quality_reasons(details: dict[str, Any]) -> list[str]:
    """Expose actionable NAV-quality issues, not normal estimates between reports."""
    data_status = str(details.get("data_status") or "").upper()
    cash_calibration_quality = str(details.get("cash_calibration_quality") or "").upper()
    receivable_quality = str(details.get("receivable_quality") or "").upper()
    notes = str(details.get("quality_notes") or "").lower()

    reasons: list[str] = []
    if cash_calibration_quality == "HIGH_RESIDUAL":
        reasons.append(
            "Kontantestimatet ligger i en periode med høy avstemmingsrest og har lavere kvalitet."
        )
    if receivable_quality == "ESTIMATED_GROSS" or "gross-estimated" in notes:
        reasons.append(
            "Minst én Bemobi-fordring er bruttoestimert fordi det mangler et rapportankre i perioden."
        )

    if (
        data_status == "DEGRADED"
        and not reasons
        and not _expected_between_reports(details)
    ):
        reasons.append(
            "NAV-data har et kvalitetsavvik utover normal estimering mellom rapportdatoer."
        )

    return list(dict.fromkeys(reasons))


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
            period = (
                f" for {target_year}"
                if target_year.isdigit() and len(target_year) == 4
                else ""
            )
            message = f"Bemobi / CVM: Ingen CVM-dokumenter funnet{period}."
        elif code == "dashboard_quality":
            reasons = _dashboard_quality_reasons(safe_details)
            if not reasons and _expected_between_reports(safe_details):
                continue
            if reasons:
                message = "Dashboardkvalitet: " + " ".join(reasons)
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
    public_warnings = (
        _public_preflight_warnings(
            preflight,
            target_date=metadata.get("target_date"),
        )
        if preflight
        else []
    )
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
        "preflight": (
            {
                "ready": bool(preflight.get("ready")),
                "blocker_count": len(preflight.get("blockers") or []),
                "warning_count": len(public_warnings),
                "warnings": public_warnings,
            }
            if preflight
            else None
        ),
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
    return await repository.first("""
        SELECT sh.checked_at, sh.status, sh.error_message, sh.metadata_json
        FROM source_health sh
        JOIN sources s ON s.id=sh.source_id
        WHERE s.code='NORGES_BANK'
        ORDER BY sh.id DESC
        LIMIT 1
        """)


async def _writer_lock(repository) -> dict[str, Any] | None:
    return await repository.first(
        "SELECT value, updated_at FROM runtime_state WHERE key=? LIMIT 1",
        (WRITER_LOCK_KEY,),
    )


async def _current_dashboard_quality(repository) -> dict[str, Any]:
    """Read the latest NAV quality cheaply, without rebuilding the full dashboard summary."""
    full = await repository.first(
        """
        SELECT as_of_at, status, components_json, quality_notes
        FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope='FULL'
        ORDER BY as_of_at DESC, id DESC
        LIMIT 1
        """,
        (FULL_NAV_CALCULATION_VERSION,),
    )
    if full is None:
        return {
            "available": False,
            "status": "MISSING",
            "data_status": "MISSING",
            "as_of_date": None,
            "reasons": [],
        }

    core = await repository.first(
        """
        SELECT status, components_json
        FROM nav_snapshots
        WHERE as_of_at=? AND calculation_version=? AND nav_scope='CORE'
        ORDER BY id DESC LIMIT 1
        """,
        (full.get("as_of_at"), CORE_NAV_CALCULATION_VERSION),
    )
    full_components = _json_object(full.get("components_json"))
    core_components = _json_object((core or {}).get("components_json"))
    cash = core_components.get("cash") if isinstance(core_components.get("cash"), dict) else {}
    otec = core_components.get("otec") if isinstance(core_components.get("otec"), dict) else {}
    ona = (
        full_components.get("other_net_assets")
        if isinstance(full_components.get("other_net_assets"), dict)
        else {}
    )
    option = ona.get("option_liability") if isinstance(ona.get("option_liability"), dict) else {}
    data_status = str(full.get("status") or "UNKNOWN").upper()
    details = {
        "data_status": data_status,
        "cash_quality": cash.get("quality"),
        "cash_calibration_quality": cash.get("calibration_quality"),
        "share_count_quality": otec.get("share_count_quality"),
        "ona_quality": ona.get("quality"),
        "receivable_quality": ona.get("receivable_quality"),
        "option_quality": option.get("quality"),
        "quality_notes": full.get("quality_notes"),
    }
    reasons = _dashboard_quality_reasons(details)
    public_status = "DEGRADED" if reasons else "OK"
    return {
        "available": True,
        "status": public_status,
        "data_status": data_status,
        "as_of_date": str(full.get("as_of_at") or "")[:10] or None,
        "reasons": reasons,
    }


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
    dashboard_quality = await _current_dashboard_quality(repository)

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
    fx_current = (
        latest_common_date is not None and str(latest_common_date) >= expected_fx_date
    )

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
        or not bool(hot_snapshot.get("valid"))
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
        "dashboard_quality": dashboard_quality,
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

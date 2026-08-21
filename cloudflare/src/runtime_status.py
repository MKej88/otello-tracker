from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

try:
    from .fx_freshness import expected_norges_bank_date, norges_bank_fx_coverage
except ImportError:
    from fx_freshness import expected_norges_bank_date, norges_bank_fx_coverage

FULL_JOB = "cloudflare_full_refresh"
FAST_JOB = "cloudflare_fast_refresh"
EXPECTED_SOURCE_CODES = (
    "NORGES_BANK",
    "B3",
    "CVM",
    "BEMOBI_IR",
    "NEWSWEB",
    "EURONEXT",
)
D1_OK_AGE_SECONDS = 75 * 60
D1_DOWN_AGE_SECONDS = 3 * 60 * 60
ERROR_TEXT_LIMIT = 800

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?token|access[_-]?token|token|secret|password|api[_-]?key)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_URL_RE = re.compile(r"https?://[^\s<>\"']+")


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


def _redact_url(match: re.Match[str]) -> str:
    value = match.group(0)
    query_at = len(value)
    for delimiter in ("?", "#"):
        position = value.find(delimiter)
        if position >= 0:
            query_at = min(query_at, position)
    return value[:query_at]


def sanitize_error_text(value: Any) -> str | None:
    """Return useful diagnostics without exposing credentials or raw request parameters."""
    text = str(value or "").strip()
    if not text:
        return None
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _JWT_RE.sub("[REDACTED_JWT]", text)
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _URL_RE.sub(_redact_url, text)
    return text[:ERROR_TEXT_LIMIT]


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
        "error_message": sanitize_error_text(row.get("error_message")),
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


async def _latest_source_health(repository) -> list[dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT s.code AS source_code, sh.checked_at, sh.status, sh.error_message
        FROM source_health sh
        JOIN sources s ON s.id=sh.source_id
        WHERE s.code IN ('NORGES_BANK','B3','CVM','BEMOBI_IR','NEWSWEB','EURONEXT')
          AND sh.id=(
              SELECT sh2.id
              FROM source_health sh2
              WHERE sh2.source_id=sh.source_id
              ORDER BY sh2.id DESC
              LIMIT 1
          )
        ORDER BY s.code
        """
    )
    by_code = {str(row.get("source_code")): row for row in rows}
    return [
        {
            "source": code,
            "status": str((by_code.get(code) or {}).get("status") or "MISSING").upper(),
            "checked_at": (by_code.get(code) or {}).get("checked_at"),
            "error_message": sanitize_error_text((by_code.get(code) or {}).get("error_message")),
        }
        for code in EXPECTED_SOURCE_CODES
    ]


async def _latest_fx_rows(repository) -> list[dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT fr.base_currency, fr.quote_currency, fr.observed_at, fr.rate,
               fr.fetched_at, s.code AS source_code
        FROM fx_rates fr
        JOIN sources s ON s.id=fr.source_id
        WHERE fr.quote_currency='NOK'
          AND fr.base_currency IN ('BRL','USD')
          AND s.code='NORGES_BANK'
        ORDER BY substr(fr.observed_at,1,10) DESC, fr.base_currency, fr.id DESC
        LIMIT 8
        """
    )
    return [
        {
            "pair": f"{row.get('base_currency')}/{row.get('quote_currency')}",
            "observed_at": row.get("observed_at"),
            "rate": row.get("rate"),
            "fetched_at": row.get("fetched_at"),
            "source": row.get("source_code"),
        }
        for row in rows
    ]


async def _recent_job_errors(repository) -> list[dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT job_name, started_at, finished_at, status, error_message
        FROM job_runs
        WHERE status IN ('FAILED','PARTIAL')
          AND error_message IS NOT NULL
          AND trim(error_message) <> ''
        ORDER BY id DESC
        LIMIT 5
        """
    )
    return [
        {
            "job_name": row.get("job_name"),
            "status": row.get("status"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "error_message": sanitize_error_text(row.get("error_message")),
        }
        for row in rows
    ]


async def _d1_activity(repository) -> dict[str, Any]:
    row = await repository.first(
        """
        SELECT
          (SELECT MAX(COALESCE(finished_at, started_at)) FROM job_runs) AS latest_job_at,
          (SELECT MAX(checked_at) FROM source_health) AS latest_source_health_at,
          (SELECT MAX(fetched_at) FROM fx_rates) AS latest_fx_write_at
        """
    ) or {}
    return {
        "latest_job_at": row.get("latest_job_at"),
        "latest_source_health_at": row.get("latest_source_health_at"),
        "latest_fx_write_at": row.get("latest_fx_write_at"),
    }


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _d1_freshness(activity: dict[str, Any], current: datetime) -> dict[str, Any]:
    timestamps = [
        parsed
        for parsed in (_parse_timestamp(value) for value in activity.values())
        if parsed is not None
    ]
    latest = max(timestamps) if timestamps else None
    age_seconds = max(0, int((current - latest).total_seconds())) if latest else None
    if age_seconds is None or age_seconds > D1_DOWN_AGE_SECONDS:
        status = "DOWN"
    elif age_seconds > D1_OK_AGE_SECONDS:
        status = "DEGRADED"
    else:
        status = "OK"
    return {
        "status": status,
        "latest_activity_at": latest.isoformat(timespec="seconds").replace("+00:00", "Z") if latest else None,
        "age_seconds": age_seconds,
        "ok_age_seconds": D1_OK_AGE_SECONDS,
        "down_age_seconds": D1_DOWN_AGE_SECONDS,
        "signals": activity,
    }


def _norges_bank_last_write(fx: dict[str, Any]) -> str | None:
    values = [
        str(item.get("latest_fetch"))
        for item in (fx.get("pairs") or {}).values()
        if item.get("latest_fetch")
    ]
    return max(values) if values else None


async def runtime_status_summary(
    repository,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    full_row = await _latest_job(repository, FULL_JOB)
    fast_row = await _latest_job(repository, FAST_JOB)
    source_health = await _latest_source_health(repository)
    fx = await norges_bank_fx_coverage(repository)
    fx_rows = await _latest_fx_rows(repository)
    recent_errors = await _recent_job_errors(repository)
    d1 = _d1_freshness(await _d1_activity(repository), current)

    full = _job_payload(full_row)
    fast = _job_payload(fast_row)
    expected_fx_date = expected_norges_bank_date(current)
    latest_common_date = fx.get("latest_common_date")
    fx_current = latest_common_date is not None and str(latest_common_date) >= expected_fx_date

    norges_bank_health = next(
        (item for item in source_health if item["source"] == "NORGES_BANK"),
        {"status": "MISSING", "checked_at": None, "error_message": None},
    )
    health_status = str(norges_bank_health.get("status") or "MISSING").upper()
    full_status = str(full.get("status") or "MISSING").upper()
    fast_status = str(fast.get("status") or "MISSING").upper()

    ready = bool(full.get("available") and fast.get("available") and latest_common_date)
    if not ready or d1["status"] == "DOWN":
        status = "DOWN"
    elif (
        not fx_current
        or full_status in {"FAILED", "PARTIAL"}
        or fast_status in {"FAILED", "PARTIAL"}
        or health_status in {"DOWN", "DEGRADED", "MISSING"}
        or d1["status"] == "DEGRADED"
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
        "sources": source_health,
        "norges_bank": {
            "status": health_status,
            "checked_at": norges_bank_health.get("checked_at"),
            "last_write_at": _norges_bank_last_write(fx),
            "error_message": norges_bank_health.get("error_message"),
        },
        "fx": {
            **fx,
            "expected_date": expected_fx_date,
            "current": fx_current,
            "latest_rows": fx_rows,
        },
        "recent_job_errors": recent_errors,
        "d1": d1,
        "security": {
            "read_only": True,
            "raw_metadata_exposed": False,
            "errors_redacted": True,
        },
    }

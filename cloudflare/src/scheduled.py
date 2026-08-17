from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

try:
    from .bmob3_ingestion import maybe_finalize_bmob3_eod, refresh_bmob3_intraday_price
    from .newsweb_buybacks import collect_newsweb_buybacks
    from .newsweb_ingestion import collect_newsweb_history
    from .otec_ingestion import maybe_finalize_otec_eod, refresh_otec_with_gap_recovery
    from .repository import D1WriteRepository
except ImportError:
    from bmob3_ingestion import maybe_finalize_bmob3_eod, refresh_bmob3_intraday_price
    from newsweb_buybacks import collect_newsweb_buybacks
    from newsweb_ingestion import collect_newsweb_history
    from otec_ingestion import maybe_finalize_otec_eod, refresh_otec_with_gap_recovery
    from repository import D1WriteRepository

FAST_REFRESH_CRON = "*/30 * * * *"
JOB_NAME = "cloudflare_fast_refresh"
OSLO_TZ = ZoneInfo("Europe/Oslo")


def _scheduled_datetime(scheduled_time_ms: Any | None) -> datetime:
    if scheduled_time_ms is None:
        return datetime.now(UTC)
    try:
        milliseconds = float(scheduled_time_ms)
    except (TypeError, ValueError):
        return datetime.now(UTC)
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _scheduled_iso(scheduled_time_ms: Any | None) -> str:
    return _scheduled_datetime(scheduled_time_ms).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _eod_is_authoritative(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "ok":
        return True
    return result.get("status") == "skipped" and result.get("reason") == "eod_already_finalized"


async def _safe_async_step(
    name: str,
    fn: Callable[[], Awaitable[Any]],
    *,
    steps: dict[str, Any],
    errors: list[dict[str, str]],
) -> Any:
    try:
        result = await fn()
        steps[name] = result
        return result
    except Exception as exc:
        error = {"step": name, "error": str(exc)[:1000], "error_type": type(exc).__name__}
        errors.append(error)
        steps[name] = {"status": "error", **error}
        return None


def _append_nested_errors(
    step: str,
    result: Any,
    *,
    errors: list[dict[str, str]],
) -> None:
    if not isinstance(result, dict):
        return
    nested = result.get("errors")
    if not isinstance(nested, list):
        return
    for item in nested:
        if not isinstance(item, dict):
            continue
        message_id = item.get("message_id")
        detail = str(item.get("error") or "ukjent NewsWeb-feil")[:800]
        prefix = f"messageId={message_id}: " if message_id is not None else ""
        errors.append(
            {
                "step": step,
                "error": (prefix + detail)[:1000],
                "error_type": "NewsWebItemError",
            }
        )


async def run_fast_refresh(
    database: Any,
    *,
    scheduled_time_ms: Any | None = None,
) -> dict[str, Any]:
    """Run bounded 30-minute ingestion and persist an auditable D1 job record."""
    repository = D1WriteRepository(database)
    scheduled_at = _scheduled_datetime(scheduled_time_ms)
    started_at = _scheduled_iso(scheduled_time_ms)
    job_id = await repository.start_job(
        job_name=JOB_NAME,
        started_at=started_at,
        metadata={
            "trigger": "cloudflare_cron",
            "cron": FAST_REFRESH_CRON,
            "phase": "15.4.4",
        },
    )

    steps: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    records_written = 0

    otec = await _safe_async_step(
        "otec_delayed",
        lambda: refresh_otec_with_gap_recovery(repository=repository, now=scheduled_at),
        steps=steps,
        errors=errors,
    )
    if isinstance(otec, dict) and otec.get("found"):
        records_written += 1

    if isinstance(otec, dict) and otec.get("status") in {"ok", "no_trade"}:
        otec_eod = await _safe_async_step(
            "otec_eod",
            lambda: maybe_finalize_otec_eod(
                repository=repository,
                now=scheduled_at,
                current_refresh=otec,
            ),
            steps=steps,
            errors=errors,
        )
        if isinstance(otec_eod, dict) and otec_eod.get("status") == "ok":
            records_written += 1
    else:
        steps["otec_eod"] = {
            "status": "skipped",
            "reason": "current_otec_refresh_failed",
        }

    bmob3_eod = await _safe_async_step(
        "bmob3_eod",
        lambda: maybe_finalize_bmob3_eod(repository=repository, now=scheduled_at),
        steps=steps,
        errors=errors,
    )
    if isinstance(bmob3_eod, dict) and bmob3_eod.get("status") == "ok":
        records_written += 1

    if _eod_is_authoritative(bmob3_eod):
        steps["bmob3_delayed"] = {
            "status": "skipped",
            "reason": "eod_finalized_for_session",
        }
    else:
        bmob3 = await _safe_async_step(
            "bmob3_delayed",
            lambda: refresh_bmob3_intraday_price(repository=repository, now=scheduled_at),
            steps=steps,
            errors=errors,
        )
        if isinstance(bmob3, dict) and bmob3.get("status") == "ok":
            records_written += 1

    newsweb_date = scheduled_at.astimezone(OSLO_TZ).date().isoformat()
    news_history = await _safe_async_step(
        "newsweb_history",
        lambda: collect_newsweb_history(repository, to_date=newsweb_date),
        steps=steps,
        errors=errors,
    )
    _append_nested_errors("newsweb_history", news_history, errors=errors)
    if isinstance(news_history, dict):
        records_written += int(news_history.get("archived") or 0)

    news_buybacks = await _safe_async_step(
        "newsweb_buybacks",
        lambda: collect_newsweb_buybacks(repository, to_date=newsweb_date),
        steps=steps,
        errors=errors,
    )
    _append_nested_errors("newsweb_buybacks", news_buybacks, errors=errors)
    if isinstance(news_buybacks, dict):
        records_written += int(news_buybacks.get("ingested") or 0)

    attempted_sources = 3
    failed_sources = len({item["step"].split("_")[0] for item in errors})
    if errors and failed_sources >= attempted_sources:
        status = "FAILED"
    elif errors:
        status = "PARTIAL"
    else:
        status = "SUCCESS"

    error_message = "; ".join(item["error"] for item in errors)[:4000] or None
    metadata = {
        "phase": "15.4.4",
        "steps": steps,
        "source_errors": errors,
        "pending_fast_paths": ["DIRTY_NAV"],
    }
    await repository.finish_job(
        job_id,
        finished_at=_now_iso(),
        status=status,
        records_written=records_written,
        error_message=error_message,
        metadata=metadata,
    )
    return {
        "status": status,
        "job_id": job_id,
        "records_written": records_written,
        "steps": steps,
        "source_errors": errors,
    }


async def run_scheduled(
    database: Any,
    *,
    cron: str,
    scheduled_time_ms: Any | None = None,
) -> dict[str, Any]:
    if cron != FAST_REFRESH_CRON:
        return {"status": "SKIPPED", "reason": "unknown_cron", "cron": cron}
    return await run_fast_refresh(database, scheduled_time_ms=scheduled_time_ms)

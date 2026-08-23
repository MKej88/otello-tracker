from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

try:
    from .bmob3_ingestion import maybe_finalize_bmob3_eod, refresh_bmob3_intraday_price
    from .dashboard_hot_snapshot import refresh_dashboard_hot_snapshot
    from .fx_freshness import repair_norges_bank_fx_if_stale
    from .job_lock import acquire_refresh_lock, release_refresh_lock, renew_refresh_lock
    from .nav_refresh import refresh_dirty_nav_layers
    from .newsweb_fast_refresh import collect_newsweb_fast
    from .oslo_calendar import is_oslo_bors_trading_day
    from .otec_ingestion import (
        EOD_FINALIZE_AFTER as OTEC_EOD_FINALIZE_AFTER,
        INTRADAY_BOOTSTRAP_AFTER as OTEC_BOOTSTRAP_AFTER,
        eod_otec_check_done,
        maybe_finalize_otec_eod,
        refresh_otec_with_gap_recovery,
    )
    from .otello_report_ingestion import process_pending_otello_reports
    from .performance_repository import PerformanceD1WriteRepository
except ImportError:
    from bmob3_ingestion import maybe_finalize_bmob3_eod, refresh_bmob3_intraday_price
    from dashboard_hot_snapshot import refresh_dashboard_hot_snapshot
    from fx_freshness import repair_norges_bank_fx_if_stale
    from job_lock import acquire_refresh_lock, release_refresh_lock, renew_refresh_lock
    from nav_refresh import refresh_dirty_nav_layers
    from newsweb_fast_refresh import collect_newsweb_fast
    from oslo_calendar import is_oslo_bors_trading_day
    from otec_ingestion import (
        EOD_FINALIZE_AFTER as OTEC_EOD_FINALIZE_AFTER,
        INTRADAY_BOOTSTRAP_AFTER as OTEC_BOOTSTRAP_AFTER,
        eod_otec_check_done,
        maybe_finalize_otec_eod,
        refresh_otec_with_gap_recovery,
    )
    from otello_report_ingestion import process_pending_otello_reports
    from performance_repository import PerformanceD1WriteRepository

FAST_REFRESH_CRON = "*/30 * * * *"
JOB_NAME = "cloudflare_fast_refresh"
OSLO_TZ = ZoneInfo("Europe/Oslo")
PHASE = "16.1"
FAST_LOCK_TTL_SECONDS = 20 * 60


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
    timings_ms: dict[str, float],
) -> Any:
    started = perf_counter()
    try:
        result = await fn()
        steps[name] = result
        return result
    except Exception as exc:
        error = {"step": name, "error": str(exc)[:1000], "error_type": type(exc).__name__}
        errors.append(error)
        steps[name] = {"status": "error", **error}
        return None
    finally:
        timings_ms[name] = round((perf_counter() - started) * 1000, 2)


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


async def _otec_refresh_plan(repository, scheduled_at: datetime) -> dict[str, Any]:
    local = scheduled_at.astimezone(OSLO_TZ)
    target_date = local.date().isoformat()
    if not is_oslo_bors_trading_day(local.date()):
        return {
            "should_poll": False,
            "reason": "not_trading_day",
            "target_date": target_date,
        }
    local_time = local.time().replace(tzinfo=None)
    if local_time < OTEC_BOOTSTRAP_AFTER:
        return {
            "should_poll": False,
            "reason": "before_bootstrap_cutoff",
            "target_date": target_date,
        }
    if local_time >= OTEC_EOD_FINALIZE_AFTER and await eod_otec_check_done(repository, target_date):
        return {
            "should_poll": False,
            "reason": "eod_already_finalized",
            "target_date": target_date,
        }
    return {"should_poll": True, "reason": "market_window", "target_date": target_date}


async def run_fast_refresh(
    database: Any,
    *,
    archive_bucket: Any | None = None,
    scheduled_time_ms: Any | None = None,
    renew_lock: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Run the bounded 30-minute ingestion path with cheap no-change behavior."""
    run_started = perf_counter()
    repository = PerformanceD1WriteRepository(database)
    scheduled_at = _scheduled_datetime(scheduled_time_ms)
    started_at = _scheduled_iso(scheduled_time_ms)
    job_id = await repository.start_job(
        job_name=JOB_NAME,
        started_at=started_at,
        metadata={
            "trigger": "cloudflare_cron",
            "cron": FAST_REFRESH_CRON,
            "phase": PHASE,
        },
    )

    steps: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    timings_ms: dict[str, float] = {}
    records_written = 0

    plan = await _safe_async_step(
        "otec_plan",
        lambda: _otec_refresh_plan(repository, scheduled_at),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    should_poll_otec = not isinstance(plan, dict) or bool(plan.get("should_poll", True))

    if should_poll_otec:
        otec = await _safe_async_step(
            "otec_delayed",
            lambda: refresh_otec_with_gap_recovery(repository=repository, now=scheduled_at),
            steps=steps,
            errors=errors,
            timings_ms=timings_ms,
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
                timings_ms=timings_ms,
            )
            if isinstance(otec_eod, dict) and otec_eod.get("status") == "ok":
                records_written += 1
        else:
            steps["otec_eod"] = {
                "status": "skipped",
                "reason": "current_otec_refresh_failed",
            }
    else:
        reason = str(plan.get("reason")) if isinstance(plan, dict) else "outside_market_window"
        target_date = plan.get("target_date") if isinstance(plan, dict) else None
        otec = {
            "status": "skipped",
            "reason": reason,
            "target_date": target_date,
            "network_fetches_avoided": True,
        }
        steps["otec_delayed"] = otec
        steps["otec_eod"] = {
            "status": "skipped",
            "reason": reason,
            "target_date": target_date,
        }
        timings_ms["otec_delayed"] = 0.0
        timings_ms["otec_eod"] = 0.0

    if renew_lock is not None:
        await renew_lock("after OTEC")

    bmob3_eod = await _safe_async_step(
        "bmob3_eod",
        lambda: maybe_finalize_bmob3_eod(repository=repository, now=scheduled_at),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if isinstance(bmob3_eod, dict) and bmob3_eod.get("status") == "ok":
        records_written += 1

    if _eod_is_authoritative(bmob3_eod):
        steps["bmob3_delayed"] = {
            "status": "skipped",
            "reason": "eod_finalized_for_session",
        }
        timings_ms["bmob3_delayed"] = 0.0
    else:
        bmob3 = await _safe_async_step(
            "bmob3_delayed",
            lambda: refresh_bmob3_intraday_price(repository=repository, now=scheduled_at),
            steps=steps,
            errors=errors,
            timings_ms=timings_ms,
        )
        if isinstance(bmob3, dict) and bmob3.get("status") == "ok":
            records_written += 1

    if renew_lock is not None:
        await renew_lock("after B3")

    newsweb_date = scheduled_at.astimezone(OSLO_TZ).date().isoformat()
    newsweb = await _safe_async_step(
        "newsweb_fast",
        lambda: collect_newsweb_fast(repository, to_date=newsweb_date),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if isinstance(newsweb, dict):
        news_history = newsweb.get("history") or {}
        news_buybacks = newsweb.get("buybacks") or {}
        steps["newsweb_history"] = news_history
        steps["newsweb_buybacks"] = news_buybacks
        records_written += int(news_history.get("archived") or 0)
        records_written += int(news_buybacks.get("ingested") or 0)
        _append_nested_errors("newsweb_history", news_history, errors=errors)
        _append_nested_errors("newsweb_buybacks", news_buybacks, errors=errors)
    else:
        steps["newsweb_history"] = {"status": "skipped", "reason": "newsweb_fast_failed"}
        steps["newsweb_buybacks"] = {"status": "skipped", "reason": "newsweb_fast_failed"}

    if renew_lock is not None:
        await renew_lock("after NewsWeb")

    if archive_bucket is None:
        report_result = {"status": "skipped", "reason": "missing_archive_bucket_binding"}
        steps["otello_reports"] = report_result
        timings_ms["otello_reports"] = 0.0
    else:
        report_result = await _safe_async_step(
            "otello_reports",
            lambda: process_pending_otello_reports(
                repository,
                archive_bucket,
                target_date=newsweb_date,
            ),
            steps=steps,
            errors=errors,
            timings_ms=timings_ms,
        )
        if isinstance(report_result, dict):
            records_written += int(report_result.get("applied") or 0)
            if int(report_result.get("review_required") or 0) > 0:
                errors.append(
                    {
                        "step": "otello_reports",
                        "error": (
                            f"{report_result.get('review_required')} Otello-rapportmelding(er) "
                            "krever kontroll; eksisterende NAV-ankre er beholdt"
                        ),
                        "error_type": "OtelloReportReviewRequired",
                    }
                )

    if renew_lock is not None:
        await renew_lock("after Otello reports")

    fx_repair = await _safe_async_step(
        "norges_bank_fx_repair",
        lambda: repair_norges_bank_fx_if_stale(
            repository,
            now=scheduled_at,
            archive_bucket=archive_bucket,
        ),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if isinstance(fx_repair, dict):
        if fx_repair.get("repaired"):
            records_written += int(fx_repair.get("rows_written") or 0)
        if fx_repair.get("status") == "partial":
            errors.append(
                {
                    "step": "norges_bank_fx_repair",
                    "error": (
                        "Norges Bank mangler fortsatt forventet valutadato "
                        f"{fx_repair.get('expected_date')}; siste felles dato er "
                        f"{fx_repair.get('latest_common_date') or 'ukjent'}"
                    ),
                    "error_type": "FxFreshnessPartial",
                }
            )

    if renew_lock is not None:
        await renew_lock("after Norges Bank FX")

    dirty_nav = await _safe_async_step(
        "dirty_nav",
        lambda: refresh_dirty_nav_layers(repository, target_date=newsweb_date),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if isinstance(dirty_nav, dict):
        records_written += len(dirty_nav.get("dirty_layers") or [])
        if dirty_nav.get("status") == "partial":
            errors.append(
                {
                    "step": "dirty_nav",
                    "error": "NAV-lag mangler nødvendige input: "
                    + ", ".join(dirty_nav.get("not_ready_layers") or []),
                    "error_type": "DirtyNavPartial",
                }
            )

    if renew_lock is not None:
        await renew_lock("after dirty NAV")

    # First-screen cache is a performance optimization, not an ingestion source. Seed it even
    # on no-change/weekend runs when it is missing; otherwise rebuild only when upstream data
    # changed. Failure must never turn an otherwise healthy market-data refresh into PARTIAL.
    hot_snapshot_errors: list[dict[str, str]] = []
    await _safe_async_step(
        "dashboard_hot_snapshot",
        lambda: refresh_dashboard_hot_snapshot(repository, force=records_written > 0),
        steps=steps,
        errors=hot_snapshot_errors,
        timings_ms=timings_ms,
    )
    if hot_snapshot_errors and isinstance(steps.get("dashboard_hot_snapshot"), dict):
        steps["dashboard_hot_snapshot"]["non_critical"] = True

    if renew_lock is not None:
        await renew_lock("after dashboard snapshot")

    attempted_sources = 4
    source_prefixes = {"otec", "bmob3", "newsweb", "otello"}
    failed_sources = len(
        {
            item["step"].split("_")[0]
            for item in errors
            if item["step"].split("_")[0] in source_prefixes
        }
    )
    if failed_sources >= attempted_sources:
        status = "FAILED"
    elif errors:
        status = "PARTIAL"
    else:
        status = "SUCCESS"

    error_message = "; ".join(item["error"] for item in errors)[:4000] or None
    total_ms = round((perf_counter() - run_started) * 1000, 2)
    metadata = {
        "phase": PHASE,
        "steps": steps,
        "source_errors": errors,
        "dirty_nav_enabled": True,
        "automatic_report_ingestion": archive_bucket is not None,
        "performance": {
            "total_ms_before_finish_job": total_ms,
            "step_timings_ms": timings_ms,
            "repository": repository.performance_metrics(),
            "newsweb_full_messages_fetched": (
                int(newsweb.get("full_messages_fetched") or 0)
                if isinstance(newsweb, dict)
                else None
            ),
            "newsweb_existing_skipped": (
                int(newsweb.get("skipped_existing") or 0)
                if isinstance(newsweb, dict)
                else None
            ),
            "otec_network_fetch_avoided": not should_poll_otec,
            "norges_bank_network_fetch_avoided": (
                bool(fx_repair.get("network_fetches_avoided"))
                if isinstance(fx_repair, dict)
                else None
            ),
        },
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
        "performance": {
            **metadata["performance"],
            "repository_after_finish_job": repository.performance_metrics(),
            "total_ms": round((perf_counter() - run_started) * 1000, 2),
        },
    }


async def run_scheduled(
    database: Any,
    *,
    cron: str,
    archive_bucket: Any | None = None,
    scheduled_time_ms: Any | None = None,
) -> dict[str, Any]:
    if cron != FAST_REFRESH_CRON:
        return {"status": "SKIPPED", "reason": "unknown_cron", "cron": cron}

    repository = PerformanceD1WriteRepository(database)
    owner = f"fast:{_scheduled_iso(scheduled_time_ms)}"
    lock = await acquire_refresh_lock(
        repository,
        owner=owner,
        ttl_seconds=FAST_LOCK_TTL_SECONDS,
    )
    if not lock.get("acquired"):
        return {
            "status": "SKIPPED",
            "reason": "refresh_lock_held",
            "cron": cron,
            "held_by": lock.get("held_by"),
            "expires_at": lock.get("expires_at"),
        }

    lock_token = lock.get("token")

    async def renew_lock(checkpoint: str) -> None:
        nonlocal lock_token
        result = await renew_refresh_lock(
            repository,
            lock_token,
            ttl_seconds=FAST_LOCK_TTL_SECONDS,
        )
        if not result.get("renewed"):
            raise RuntimeError(
                "fast refresh writer lease lost at "
                f"{checkpoint}; held_by={result.get('held_by')} "
                f"expires_at={result.get('expires_at')}"
            )
        lock_token = result.get("token")

    try:
        return await run_fast_refresh(
            database,
            archive_bucket=archive_bucket,
            scheduled_time_ms=scheduled_time_ms,
            renew_lock=renew_lock,
        )
    finally:
        await release_refresh_lock(repository, lock_token)

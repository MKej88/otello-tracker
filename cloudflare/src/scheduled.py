from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Awaitable, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

try:
    from .bemobi_distribution_sync import sync_confirmed_bemobi_distribution_cash
    from .bmob3_ingestion import maybe_finalize_bmob3_eod, refresh_bmob3_intraday_price
    from .dashboard_hot_snapshot import refresh_dashboard_hot_snapshot
    from .fx_freshness import repair_norges_bank_fx_if_stale
    from .job_lock import acquire_refresh_lock, release_refresh_lock, renew_refresh_lock
    from .life360_market_data import repair_life360_lif_if_stale
    from .nav_refresh import refresh_dirty_nav_layers
    from .newsweb_fast_refresh import collect_newsweb_fast
    from .oslo_calendar import is_oslo_bors_trading_day
    from .otec_activity import refresh_otec_daily_activity
    from .otec_ingestion import (
        EOD_FINALIZE_AFTER as OTEC_EOD_FINALIZE_AFTER,
        INTRADAY_BOOTSTRAP_AFTER as OTEC_BOOTSTRAP_AFTER,
        eod_otec_check_done,
        maybe_finalize_otec_eod,
        refresh_otec_with_gap_recovery,
    )
    from .otello_interest_income import sync_interest_income_anchors_from_report_result
    from .otello_report_ingestion import process_pending_otello_reports
    from .performance_repository import PerformanceD1WriteRepository
except ImportError:
    from bemobi_distribution_sync import sync_confirmed_bemobi_distribution_cash
    from bmob3_ingestion import maybe_finalize_bmob3_eod, refresh_bmob3_intraday_price
    from dashboard_hot_snapshot import refresh_dashboard_hot_snapshot
    from fx_freshness import repair_norges_bank_fx_if_stale
    from job_lock import acquire_refresh_lock, release_refresh_lock, renew_refresh_lock
    from life360_market_data import repair_life360_lif_if_stale
    from nav_refresh import refresh_dirty_nav_layers
    from newsweb_fast_refresh import collect_newsweb_fast
    from oslo_calendar import is_oslo_bors_trading_day
    from otec_activity import refresh_otec_daily_activity
    from otec_ingestion import (
        EOD_FINALIZE_AFTER as OTEC_EOD_FINALIZE_AFTER,
        INTRADAY_BOOTSTRAP_AFTER as OTEC_BOOTSTRAP_AFTER,
        eod_otec_check_done,
        maybe_finalize_otec_eod,
        refresh_otec_with_gap_recovery,
    )
    from otello_interest_income import sync_interest_income_anchors_from_report_result
    from otello_report_ingestion import process_pending_otello_reports
    from performance_repository import PerformanceD1WriteRepository

FAST_REFRESH_CRON = "*/30 * * * *"
JOB_NAME = "cloudflare_fast_refresh"
OSLO_TZ = ZoneInfo("Europe/Oslo")
PHASE = "16.2"
FAST_LOCK_TTL_SECONDS = 20 * 60


async def _skip_lock_renewal(_checkpoint: str) -> None:
    """Behold samme kallform når kjøringen ikke har en lås å fornye."""


def _scheduled_datetime(scheduled_time_ms: Any | None) -> datetime:
    if scheduled_time_ms is None:
        return datetime.now(UTC)
    try:
        milliseconds = float(scheduled_time_ms)
    except (TypeError, ValueError):
        return datetime.now(UTC)
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _scheduled_iso(scheduled_time_ms: Any | None) -> str:
    return (
        _scheduled_datetime(scheduled_time_ms)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _eod_is_authoritative(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "ok":
        return True
    return (
        result.get("status") == "skipped"
        and result.get("reason") == "eod_already_finalized"
    )


def _fast_refresh_records_written(steps: dict[str, Any]) -> int:
    """Count writes from the recorded step results after a fast refresh."""

    def result(name: str) -> dict[str, Any]:
        value = steps.get(name)
        return value if isinstance(value, dict) else {}

    total = sum(
        int(result(step_name).get(field_name) or 0)
        for step_name, field_name in (
            ("otec_activity", "written"),
            ("newsweb_history", "archived"),
            ("newsweb_buybacks", "ingested"),
            ("otello_reports", "applied"),
            ("otello_interest", "written"),
            ("life360_lif_repair", "rows_written"),
            ("bemobi_distribution_cash", "rows_written"),
            ("bemobi_distribution_cash", "rows_updated"),
        )
    )
    total += sum(
        1
        for step_name in ("otec_eod", "bmob3_eod", "bmob3_delayed")
        if result(step_name).get("status") == "ok"
    )
    total += int(bool(result("otec_delayed").get("found")))

    fx_repair = result("norges_bank_fx_repair")
    if fx_repair.get("repaired"):
        total += int(fx_repair.get("rows_written") or 0)

    total += len(result("dirty_nav").get("dirty_layers") or [])
    return total


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
        error = {
            "step": name,
            "error": str(exc)[:1000],
            "error_type": type(exc).__name__,
        }
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
    if local_time >= OTEC_EOD_FINALIZE_AFTER and await eod_otec_check_done(
        repository, target_date
    ):
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
    renew = renew_lock if renew_lock is not None else _skip_lock_renewal

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
            lambda: refresh_otec_with_gap_recovery(
                repository=repository, now=scheduled_at
            ),
            steps=steps,
            errors=errors,
            timings_ms=timings_ms,
        )
        if isinstance(otec, dict) and otec.get("status") in {"ok", "no_trade"}:
            await _safe_async_step(
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
        else:
            steps["otec_eod"] = {
                "status": "skipped",
                "reason": "current_otec_refresh_failed",
            }
    else:
        reason = (
            str(plan.get("reason"))
            if isinstance(plan, dict)
            else "outside_market_window"
        )
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

    await _safe_async_step(
        "otec_activity",
        lambda: refresh_otec_daily_activity(repository, now=scheduled_at),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    await renew("after OTEC")

    bmob3_eod = await _safe_async_step(
        "bmob3_eod",
        lambda: maybe_finalize_bmob3_eod(repository=repository, now=scheduled_at),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if _eod_is_authoritative(bmob3_eod):
        steps["bmob3_delayed"] = {
            "status": "skipped",
            "reason": "eod_finalized_for_session",
        }
        timings_ms["bmob3_delayed"] = 0.0
    else:
        await _safe_async_step(
            "bmob3_delayed",
            lambda: refresh_bmob3_intraday_price(
                repository=repository, now=scheduled_at
            ),
            steps=steps,
            errors=errors,
            timings_ms=timings_ms,
        )

    await renew("after B3")

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
        _append_nested_errors("newsweb_history", news_history, errors=errors)
        _append_nested_errors("newsweb_buybacks", news_buybacks, errors=errors)
    else:
        steps["newsweb_history"] = {
            "status": "skipped",
            "reason": "newsweb_fast_failed",
        }
        steps["newsweb_buybacks"] = {
            "status": "skipped",
            "reason": "newsweb_fast_failed",
        }

    await renew("after NewsWeb")

    if archive_bucket is None:
        report_result = {
            "status": "skipped",
            "reason": "missing_archive_bucket_binding",
        }
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

    interest_result = await _safe_async_step(
        "otello_interest",
        lambda: sync_interest_income_anchors_from_report_result(
            repository, report_result
        ),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if isinstance(interest_result, dict):
        _append_nested_errors("otello_interest", interest_result, errors=errors)

    await renew("after Otello reports")

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

    await renew("after Norges Bank FX")

    life360_repair = await _safe_async_step(
        "life360_lif_repair",
        lambda: repair_life360_lif_if_stale(
            repository,
            target_date=newsweb_date,
            archive_bucket=archive_bucket,
            force_refresh=True,
        ),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if isinstance(life360_repair, dict):
        if life360_repair.get("status") == "partial":
            errors.append(
                {
                    "step": "life360_lif_repair",
                    "error": (
                        "Life360 LIF-kurs er fortsatt for gammel etter reparasjon; "
                        f"siste kursdato={life360_repair.get('latest_price_date') or 'ukjent'}"
                    ),
                    "error_type": "Life360PriceFreshnessPartial",
                }
            )

    await renew("after Life360 LIF repair")

    bemobi_distribution_cash = await _safe_async_step(
        "bemobi_distribution_cash",
        lambda: sync_confirmed_bemobi_distribution_cash(
            repository,
            target_date=newsweb_date,
        ),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if isinstance(bemobi_distribution_cash, dict):
        if bemobi_distribution_cash.get("status") == "partial":
            skipped = bemobi_distribution_cash.get("skipped") or []
            reasons = sorted(
                {
                    str(item.get("reason") or "ukjent")
                    for item in skipped
                    if isinstance(item, dict)
                }
            )
            reason_text = ", ".join(reasons) or "ukjent årsak"
            errors.append(
                {
                    "step": "bemobi_distribution_cash",
                    "error": (
                        f"{len(skipped)} bekreftede Bemobi-utbetaling(er) kunne ikke "
                        f"materialiseres ({reason_text})"
                    ),
                    "error_type": "BemobiDistributionCashPartial",
                }
            )

    await renew("after Bemobi distribution cash")

    dirty_nav = await _safe_async_step(
        "dirty_nav",
        lambda: refresh_dirty_nav_layers(repository, target_date=newsweb_date),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if isinstance(dirty_nav, dict):
        if dirty_nav.get("status") == "partial":
            errors.append(
                {
                    "step": "dirty_nav",
                    "error": "NAV-lag mangler nødvendige input: "
                    + ", ".join(dirty_nav.get("not_ready_layers") or []),
                    "error_type": "DirtyNavPartial",
                }
            )

    await renew("after dirty NAV")

    records_written = _fast_refresh_records_written(steps)

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

    await renew("after dashboard snapshot")

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
        "automatic_interest_income_ingestion": True,
        "automatic_bemobi_distribution_cash": True,
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
    owner = f"fast:{_scheduled_iso(scheduled_time_ms)}:{uuid4().hex}"
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

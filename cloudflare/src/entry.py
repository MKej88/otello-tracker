from __future__ import annotations

import hashlib
import json
import sys
import types
from datetime import UTC, date, datetime, timedelta

from workers import WorkflowEntrypoint, WorkerEntrypoint

import oslo_calendar

_src_package = sys.modules.get("src")
if _src_package is None:
    _src_package = types.ModuleType("src")
    _src_package.__path__ = []
    sys.modules["src"] = _src_package
sys.modules.setdefault("src.oslo_calendar", oslo_calendar)

from app import app  # noqa: E402
from snapshot_drill import R2SnapshotDrillWorkflow  # noqa: E402,F401

FULL_REFRESH_LOCK_TTL_SECONDS = 3 * 60 * 60


def _event_value(event, key: str):
    try:
        return event[key]
    except (KeyError, TypeError):
        return None


def _nested_value(value, key: str):
    if value is None:
        return None
    try:
        return value[key]
    except (KeyError, TypeError):
        return None


def _workflow_payload(event):
    """Normalize Cloudflare Workflow payloads from bindings and REST-created instances.

    The REST create-instance API accepts ``params`` as a JSON-encoded string. Depending on
    runtime shape, Python Workers can therefore receive ``event.payload`` as either a mapping
    or that JSON string. Keep manual verification deterministic by accepting both forms.
    """
    payload = _event_value(event, "payload")
    if payload is None:
        payload = _event_value(event, "params")
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None
    return payload


def _workflow_target_date(event) -> str:
    payload = _workflow_payload(event)
    explicit = _nested_value(payload, "target_date")
    if explicit:
        return datetime.fromisoformat(str(explicit)).date().isoformat()

    schedule = _event_value(event, "schedule")
    scheduled_ms = _nested_value(schedule, "scheduledTime")
    if scheduled_ms is not None:
        scheduled_day = datetime.fromtimestamp(float(scheduled_ms) / 1000, tz=UTC).date()
        return (scheduled_day - timedelta(days=1)).isoformat()
    return datetime.now(UTC).date().isoformat()


def _workflow_trigger(event) -> str:
    schedule = _event_value(event, "schedule")
    cron = _nested_value(schedule, "cron")
    return f"workflow_schedule:{cron}" if cron else "workflow_manual"


def _workflow_instance_key(event) -> str:
    """Return a stable, non-sensitive key unique to one Cloudflare Workflow instance.

    Cloudflare exposes ``instanceId`` on every Workflow event. The writer-lock owner must use
    this instance identity rather than only target date/trigger; otherwise two manual runs on
    the same day can be mistaken for the same lock owner and write concurrently.
    """
    instance_id = _event_value(event, "instanceId")
    if instance_id is None:
        try:
            instance_id = getattr(event, "instanceId")
        except (AttributeError, TypeError):
            instance_id = None
    if instance_id is None or not str(instance_id).strip():
        raise RuntimeError("Cloudflare Workflow event missing instanceId")
    return hashlib.sha256(str(instance_id).encode("utf-8")).hexdigest()[:20]


def _history_year_windows(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split a one-time historical rebuild into bounded Workflow steps by calendar year."""
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if current > end:
        return []
    windows: list[tuple[str, str]] = []
    while current <= end:
        year_end = min(date(current.year, 12, 31), end)
        windows.append((current.isoformat(), year_end.isoformat()))
        current = year_end + timedelta(days=1)
    return windows


def _aggregate_history_rebuild(chunks: list[dict]) -> dict:
    failures = []
    largest_changes = []
    repository_metrics = []
    cash_anchors_updated = 0
    cash_movements_updated = 0
    for chunk in chunks:
        failures.extend(chunk.get("failures") or [])
        largest_changes.extend(chunk.get("largest_changes") or [])
        metrics = chunk.get("repository")
        if metrics:
            repository_metrics.append(metrics)
        normalization = chunk.get("cash_normalization") or {}
        cash_anchors_updated += int(normalization.get("cash_anchors_updated") or 0)
        cash_movements_updated += int(normalization.get("cash_movements_updated") or 0)

    largest_changes.sort(key=lambda item: float(item.get("absolute_change_nok") or 0), reverse=True)
    ok = all(chunk.get("status") == "ok" for chunk in chunks)
    return {
        "status": "ok" if ok else "partial",
        "chunks": len(chunks),
        "from": chunks[0].get("from") if chunks else None,
        "to": chunks[-1].get("to") if chunks else None,
        "dates_seen": sum(int(chunk.get("dates_seen") or 0) for chunk in chunks),
        "full_dates_seen": sum(int(chunk.get("full_dates_seen") or 0) for chunk in chunks),
        "dates_changed": sum(int(chunk.get("dates_changed") or 0) for chunk in chunks),
        "dates_unchanged": sum(int(chunk.get("dates_unchanged") or 0) for chunk in chunks),
        "dates_not_ready": sum(int(chunk.get("dates_not_ready") or 0) for chunk in chunks),
        "largest_changes": largest_changes[:10],
        "failures": failures[:25],
        "cash_normalization": {
            "cash_anchors_updated": cash_anchors_updated,
            "cash_movements_updated": cash_movements_updated,
        },
        "repository_chunks": repository_metrics,
        "fx_policy": "NORGES_BANK_DIRECT_NOK_PREFERRED_ECB_FALLBACK",
    }


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        import asgi

        return await asgi.fetch(app, request.js_object, self.env)

    async def scheduled(self, controller, env, ctx):
        from scheduled import run_scheduled

        bindings = env if env is not None else self.env
        return await run_scheduled(
            bindings.DB,
            cron=str(controller.cron),
            archive_bucket=bindings.SOURCE_ARCHIVE,
            scheduled_time_ms=controller.scheduledTime,
        )


class FullRefreshWorkflow(WorkflowEntrypoint):
    """Durable full refresh protected from concurrent fast-path writes."""

    async def run(self, event, step):
        from b3_full_refresh import refresh_bmob3_close
        from bemobi_web_refresh_runtime import refresh_bemobi_web
        from cvm_full_refresh import refresh_bemobi_cvm
        from full_refresh import (
            error_result,
            finish_full_refresh,
            preflight,
            refresh_nav,
            start_full_refresh,
        )
        from fx_history_rebuild import rebuild_existing_nav_with_norges_bank
        from job_lock import acquire_refresh_lock, release_refresh_lock, renew_refresh_lock
        from life360_market_data import refresh_life360_market_data
        from newsweb_pdf_refresh import enrich_newsweb_buybacks_if_due
        from newsweb_reconciliation import reconcile_newsweb
        from norges_bank_full_refresh import refresh_norges_bank_fx
        from otec_workflow_recovery import ensure_otec_eod
        from otello_report_ingestion import process_pending_otello_reports
        from performance_repository import PerformanceD1WriteRepository
        from r2_snapshot import archive_d1_snapshot
        from status_email import send_full_refresh_status_email

        target_date = _workflow_target_date(event)
        trigger = _workflow_trigger(event)
        source_results = {}
        lock_owner = f"full:{target_date}:{_workflow_instance_key(event)}"

        @step.do(
            "acquire full refresh writer lock",
            config={"retries": {"limit": 8, "delay": "1 minute"}, "timeout": "2 minutes"},
        )
        async def lock_step():
            repository = PerformanceD1WriteRepository(self.env.DB)
            result = await acquire_refresh_lock(
                repository,
                owner=lock_owner,
                ttl_seconds=FULL_REFRESH_LOCK_TTL_SECONDS,
            )
            if not result.get("acquired"):
                raise RuntimeError(
                    "refresh writer lock held by "
                    f"{result.get('held_by')} until {result.get('expires_at')}"
                )
            return result

        lock_result = await lock_step()
        lock_token = lock_result.get("token")

        async def renew_lock(checkpoint: str):
            nonlocal lock_token
            current_token = lock_token

            @step.do(
                f"renew full refresh writer lock {checkpoint}",
                config={"retries": {"limit": 3, "delay": "5 seconds"}, "timeout": "2 minutes"},
            )
            async def renew_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await renew_refresh_lock(
                    repository,
                    current_token,
                    ttl_seconds=FULL_REFRESH_LOCK_TTL_SECONDS,
                )
                if not result.get("renewed"):
                    raise RuntimeError(
                        "refresh writer lease lost at "
                        f"{checkpoint}; held_by={result.get('held_by')} "
                        f"expires_at={result.get('expires_at')}"
                    )
                return result

            result = await renew_step()
            lock_token = result.get("token")
            return result

        @step.do(
            "release full refresh writer lock",
            config={"retries": {"limit": 3, "delay": "5 seconds"}, "timeout": "2 minutes"},
        )
        async def release_step():
            repository = PerformanceD1WriteRepository(self.env.DB)
            released = await release_refresh_lock(repository, lock_token)
            return {"released": released, "owner": lock_owner}

        try:
            @step.do(
                "start full refresh",
                config={"retries": {"limit": 2, "delay": "5 seconds"}, "timeout": "2 minutes"},
            )
            async def start_step():
                return await start_full_refresh(self.env.DB, target_date=target_date, trigger=trigger)

            job_id = await start_step()
            await renew_lock("after start")

            @step.do(
                "refresh Norges Bank FX",
                config={"retries": {"limit": 3, "delay": "30 seconds"}, "timeout": "10 minutes"},
            )
            async def norges_bank_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await refresh_norges_bank_fx(
                    repository,
                    target_date=target_date,
                    archive_bucket=self.env.SOURCE_ARCHIVE,
                )
                return {**result, "repository": repository.performance_metrics()}

            try:
                source_results["norges_bank"] = await norges_bank_step()
            except Exception as exc:
                source_results["norges_bank"] = error_result(exc)
            await renew_lock("after Norges Bank")

            if source_results["norges_bank"].get("history_backfill"):
                history_start = str(source_results["norges_bank"]["history_start_required"])
                history_chunks: list[dict] = []
                for chunk_start, chunk_end in _history_year_windows(history_start, target_date):
                    chunk_year = chunk_start[:4]
                    history_chunk_start = chunk_start
                    history_chunk_end = chunk_end

                    @step.do(
                        f"rebuild historical NAV with Norges Bank FX {chunk_year}",
                        config={"retries": {"limit": 2, "delay": "1 minute"}, "timeout": "10 minutes"},
                    )
                    async def norges_bank_history_nav_step():
                        repository = PerformanceD1WriteRepository(self.env.DB)
                        result = await rebuild_existing_nav_with_norges_bank(
                            repository,
                            start_date=history_chunk_start,
                            end_date=history_chunk_end,
                        )
                        return {**result, "repository": repository.performance_metrics()}

                    try:
                        history_chunks.append(await norges_bank_history_nav_step())
                    except Exception as exc:
                        history_chunks.append(
                            {
                                **error_result(exc),
                                "status": "partial",
                                "from": chunk_start,
                                "to": chunk_end,
                            }
                        )
                    await renew_lock(f"after Norges Bank history {chunk_year}")

                history_nav = _aggregate_history_rebuild(history_chunks)
                source_results["norges_bank"]["history_nav_rebuild"] = history_nav
                if history_nav.get("status") != "ok":
                    source_results["norges_bank"]["status"] = "partial"

            @step.do(
                "refresh Life360 market data",
                config={"retries": {"limit": 2, "delay": "1 minute"}, "timeout": "10 minutes"},
            )
            async def life360_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await refresh_life360_market_data(
                    repository,
                    target_date=target_date,
                    archive_bucket=self.env.SOURCE_ARCHIVE,
                )
                return {**result, "repository": repository.performance_metrics()}

            try:
                source_results["life360"] = await life360_step()
            except Exception as exc:
                source_results["life360"] = error_result(exc)
            await renew_lock("after Life360")

            @step.do(
                "refresh B3 COTAHIST",
                config={"retries": {"limit": 4, "delay": "1 minute"}, "timeout": "5 minutes"},
            )
            async def b3_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await refresh_bmob3_close(
                    repository,
                    target_date=target_date,
                    archive_bucket=self.env.SOURCE_ARCHIVE,
                )
                return {**result, "repository": repository.performance_metrics()}

            try:
                source_results["b3"] = await b3_step()
            except Exception as exc:
                source_results["b3"] = error_result(exc)
            await renew_lock("after B3")

            @step.do(
                "refresh Bemobi CVM",
                config={"retries": {"limit": 2, "delay": "2 minutes"}, "timeout": "15 minutes"},
            )
            async def cvm_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await refresh_bemobi_cvm(repository, target_date=target_date)
                return {**result, "repository": repository.performance_metrics()}

            try:
                source_results["cvm"] = await cvm_step()
            except Exception as exc:
                source_results["cvm"] = error_result(exc)
            await renew_lock("after CVM")

            @step.do(
                "refresh Bemobi investor web facts",
                config={"retries": {"limit": 2, "delay": "1 minute"}, "timeout": "20 minutes"},
            )
            async def bemobi_web_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await refresh_bemobi_web(
                    repository,
                    target_date=target_date,
                    archive_bucket=self.env.SOURCE_ARCHIVE,
                )
                return {**result, "repository": repository.performance_metrics()}

            try:
                source_results["bemobi_web"] = await bemobi_web_step()
            except Exception as exc:
                source_results["bemobi_web"] = error_result(exc)
            await renew_lock("after Bemobi web")

            @step.do(
                "reconcile NewsWeb",
                config={"retries": {"limit": 3, "delay": "1 minute"}, "timeout": "15 minutes"},
            )
            async def newsweb_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await reconcile_newsweb(repository, target_date=target_date)
                return {**result, "repository": repository.performance_metrics()}

            try:
                source_results["newsweb"] = await newsweb_step()
            except Exception as exc:
                source_results["newsweb"] = error_result(exc)
            await renew_lock("after NewsWeb")

            @step.do(
                "archive NewsWeb buyback PDFs",
                config={"retries": {"limit": 2, "delay": "1 minute"}, "timeout": "20 minutes"},
            )
            async def newsweb_pdf_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await enrich_newsweb_buybacks_if_due(
                    repository,
                    self.env.SOURCE_ARCHIVE,
                    target_date=target_date,
                )
                return {**result, "repository": repository.performance_metrics()}

            try:
                source_results["newsweb_attachments"] = await newsweb_pdf_step()
            except Exception as exc:
                source_results["newsweb_attachments"] = error_result(exc)
            await renew_lock("after NewsWeb attachments")

            @step.do(
                "ingest Otello financial reports",
                config={"retries": {"limit": 2, "delay": "1 minute"}, "timeout": "20 minutes"},
            )
            async def report_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await process_pending_otello_reports(
                    repository,
                    self.env.SOURCE_ARCHIVE,
                    target_date=target_date,
                )
                return {**result, "repository": repository.performance_metrics()}

            try:
                source_results["otello_reports"] = await report_step()
            except Exception as exc:
                source_results["otello_reports"] = error_result(exc)
            await renew_lock("after Otello reports")

            @step.do(
                "ensure OTEC EOD",
                config={"retries": {"limit": 2, "delay": "1 minute"}, "timeout": "10 minutes"},
            )
            async def otec_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await ensure_otec_eod(
                    repository,
                    self.env.SOURCE_ARCHIVE,
                    target_date=target_date,
                )
                return {**result, "repository": repository.performance_metrics()}

            try:
                source_results["otec_recovery"] = await otec_step()
            except Exception as exc:
                source_results["otec_recovery"] = error_result(exc)
            await renew_lock("after OTEC")

            @step.do(
                "refresh dirty NAV",
                config={"retries": {"limit": 2, "delay": "30 seconds"}, "timeout": "5 minutes"},
            )
            async def nav_step():
                return await refresh_nav(self.env.DB, target_date=target_date)

            try:
                nav_result = await nav_step()
            except Exception as exc:
                nav_result = error_result(exc)
            await renew_lock("after NAV")

            @step.do(
                "D1 data health preflight",
                config={"retries": {"limit": 1, "delay": "15 seconds"}, "timeout": "3 minutes"},
            )
            async def preflight_step():
                return await preflight(self.env.DB, target_date=target_date)

            try:
                preflight_result = await preflight_step()
            except Exception as exc:
                preflight_result = {
                    **error_result(exc),
                    "ready": False,
                    "blockers": [{"name": "preflight_execution", "status": "FAIL"}],
                    "warnings": [],
                }
            await renew_lock("after preflight")

            @step.do(
                "archive D1 logical snapshot",
                config={"retries": {"limit": 2, "delay": "30 seconds"}, "timeout": "10 minutes"},
            )
            async def snapshot_step():
                repository = PerformanceD1WriteRepository(self.env.DB)
                result = await archive_d1_snapshot(
                    repository,
                    self.env.SOURCE_ARCHIVE,
                    target_date=target_date,
                    preflight_status=preflight_result.get("status"),
                )
                return {**result, "repository": repository.performance_metrics()}

            try:
                archive_result = await snapshot_step()
            except Exception as exc:
                archive_result = error_result(exc)
            await renew_lock("after snapshot")

            @step.do(
                "finish full refresh",
                config={"retries": {"limit": 3, "delay": "10 seconds"}, "timeout": "3 minutes"},
            )
            async def finish_step():
                return await finish_full_refresh(
                    self.env.DB,
                    job_id=job_id,
                    target_date=target_date,
                    source_results=source_results,
                    nav_result=nav_result,
                    preflight_result=preflight_result,
                    archive_result=archive_result,
                )

            result = await finish_step()

            @step.do(
                "send nightly status email",
                config={"retries": {"limit": 1, "delay": "10 seconds"}, "timeout": "2 minutes"},
            )
            async def email_step():
                return await send_full_refresh_status_email(self.env, result)

            await email_step()
            return result
        except Exception as exc:
            workflow_error = str(exc)[:1000] or type(exc).__name__
            failure_result = {
                "status": "FAILED",
                "job_id": locals().get("job_id"),
                "target_date": target_date,
                "records_written": 0,
                "source_health": {},
                "critical_errors": [
                    {
                        "step": "workflow",
                        "error": workflow_error,
                    }
                ],
                "preflight": locals().get("preflight_result", {}),
                "errors": [
                    {
                        "step": "workflow",
                        "error": workflow_error,
                    }
                ],
            }

            failure_job_id = failure_result.get("job_id")
            if failure_job_id is not None:
                @step.do(
                    "finalize failed full refresh",
                    config={"retries": {"limit": 3, "delay": "10 seconds"}, "timeout": "2 minutes"},
                )
                async def failure_finalize_step():
                    repository = PerformanceD1WriteRepository(self.env.DB)
                    updated = await repository.fail_job_if_running(
                        int(failure_job_id),
                        finished_at=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        error_message=workflow_error,
                        metadata={
                            "target_date": target_date,
                            "failure": {"step": "workflow", "error": workflow_error},
                        },
                    )
                    return {"updated": updated, "job_id": int(failure_job_id)}

                try:
                    failure_result["job_finalization"] = await failure_finalize_step()
                except Exception as finalize_exc:
                    finalize_error = str(finalize_exc)[:1000] or type(finalize_exc).__name__
                    failure_result["job_finalization"] = {
                        "updated": False,
                        "error": finalize_error,
                    }
                    failure_result["errors"].append(
                        {"step": "failure_finalization", "error": finalize_error}
                    )

            @step.do(
                "send nightly failure status email",
                config={"retries": {"limit": 1, "delay": "10 seconds"}, "timeout": "2 minutes"},
            )
            async def failure_email_step():
                return await send_full_refresh_status_email(self.env, failure_result)

            await failure_email_step()
            raise
        finally:
            await release_step()
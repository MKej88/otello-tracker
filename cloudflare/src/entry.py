from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta

from workers import WorkflowEntrypoint, WorkerEntrypoint

import oslo_calendar

_src_package = sys.modules.get("src")
if _src_package is None:
    _src_package = types.ModuleType("src")
    _src_package.__path__ = []
    sys.modules["src"] = _src_package
sys.modules.setdefault("src.oslo_calendar", oslo_calendar)

from app import app  # noqa: E402

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


def _workflow_target_date(event) -> str:
    payload = _event_value(event, "payload")
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
            scheduled_time_ms=controller.scheduledTime,
        )


class FullRefreshWorkflow(WorkflowEntrypoint):
    """Durable full refresh protected from concurrent fast-path writes."""

    async def run(self, event, step):
        from b3_full_refresh import refresh_bmob3_close
        from cvm_full_refresh import refresh_bemobi_cvm
        from ecb_full_refresh import refresh_ecb_fx
        from full_refresh import (
            error_result,
            finish_full_refresh,
            preflight,
            refresh_nav,
            start_full_refresh,
        )
        from job_lock import acquire_refresh_lock, release_refresh_lock
        from newsweb_pdf_refresh import enrich_newsweb_buybacks_if_due
        from newsweb_reconciliation import reconcile_newsweb
        from otec_workflow_recovery import ensure_otec_eod
        from performance_repository import PerformanceD1WriteRepository
        from r2_snapshot import archive_d1_snapshot

        target_date = _workflow_target_date(event)
        trigger = _workflow_trigger(event)
        source_results = {}
        lock_owner = f"full:{target_date}:{trigger}"

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

        @step.do(
            "start full refresh",
            config={"retries": {"limit": 2, "delay": "5 seconds"}, "timeout": "2 minutes"},
        )
        async def start_step():
            return await start_full_refresh(self.env.DB, target_date=target_date, trigger=trigger)

        job_id = await start_step()

        @step.do(
            "refresh ECB FX",
            config={"retries": {"limit": 3, "delay": "30 seconds"}, "timeout": "3 minutes"},
        )
        async def ecb_step():
            repository = PerformanceD1WriteRepository(self.env.DB)
            result = await refresh_ecb_fx(
                repository,
                target_date=target_date,
                archive_bucket=self.env.SOURCE_ARCHIVE,
            )
            return {**result, "repository": repository.performance_metrics()}

        try:
            source_results["ecb"] = await ecb_step()
        except Exception as exc:
            source_results["ecb"] = error_result(exc)

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
            "release full refresh writer lock",
            config={"retries": {"limit": 3, "delay": "5 seconds"}, "timeout": "2 minutes"},
        )
        async def release_step():
            repository = PerformanceD1WriteRepository(self.env.DB)
            released = await release_refresh_lock(repository, lock_result.get("token"))
            return {"released": released, "owner": lock_owner}

        await release_step()
        return result

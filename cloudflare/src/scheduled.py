from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

try:
    from .otec_ingestion import refresh_otec_intraday
    from .repository import D1WriteRepository
except ImportError:
    from otec_ingestion import refresh_otec_intraday
    from repository import D1WriteRepository

FAST_REFRESH_CRON = "*/30 * * * *"
JOB_NAME = "cloudflare_fast_refresh"


def _scheduled_iso(scheduled_time_ms: Any | None) -> str:
    if scheduled_time_ms is None:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        milliseconds = float(scheduled_time_ms)
    except (TypeError, ValueError):
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def run_fast_refresh(
    database: Any,
    *,
    scheduled_time_ms: Any | None = None,
) -> dict[str, Any]:
    """Run the Phase 15.4 fast path and persist an auditable D1 job record."""
    repository = D1WriteRepository(database)
    started_at = _scheduled_iso(scheduled_time_ms)
    job_id = await repository.start_job(
        job_name=JOB_NAME,
        started_at=started_at,
        metadata={
            "trigger": "cloudflare_cron",
            "cron": FAST_REFRESH_CRON,
            "phase": "15.4.1",
        },
    )

    try:
        otec = await refresh_otec_intraday(repository=repository)
        records_written = 1 if otec.get("found") else 0
        metadata = {
            "phase": "15.4.1",
            "otec": otec,
            "pending_fast_paths": ["BMOB3", "NEWSWEB", "DIRTY_NAV"],
        }
        await repository.finish_job(
            job_id,
            finished_at=_now_iso(),
            status="SUCCESS",
            records_written=records_written,
            metadata=metadata,
        )
        return {
            "status": "SUCCESS",
            "job_id": job_id,
            "records_written": records_written,
            "otec": otec,
        }
    except Exception as exc:
        await repository.finish_job(
            job_id,
            finished_at=_now_iso(),
            status="FAILED",
            error_message=str(exc)[:1000],
            metadata={
                "phase": "15.4.1",
                "failed_component": "OTEC",
                "error_type": type(exc).__name__,
            },
        )
        raise


async def run_scheduled(
    database: Any,
    *,
    cron: str,
    scheduled_time_ms: Any | None = None,
) -> dict[str, Any]:
    if cron != FAST_REFRESH_CRON:
        return {"status": "SKIPPED", "reason": "unknown_cron", "cron": cron}
    return await run_fast_refresh(database, scheduled_time_ms=scheduled_time_ms)

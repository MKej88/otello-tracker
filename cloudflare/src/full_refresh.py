from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

try:
    from .d1_preflight import run_d1_preflight
    from .nav_refresh import refresh_dirty_nav_layers
    from .performance_repository import PerformanceD1WriteRepository
except ImportError:
    from d1_preflight import run_d1_preflight
    from nav_refresh import refresh_dirty_nav_layers
    from performance_repository import PerformanceD1WriteRepository

JOB_NAME = "cloudflare_full_refresh"
PHASE = "16.2"
_SOURCE_CODE_BY_STEP = {
    "ecb": "ECB",
    "b3": "B3",
    "cvm": "CVM",
    "bemobi_web": "BEMOBI_IR",
    "newsweb": "NEWSWEB",
    "newsweb_attachments": "NEWSWEB",
    "otello_reports": "NEWSWEB",
    "otec_recovery": "EURONEXT",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def error_result(exc: Exception) -> dict[str, Any]:
    return {
        "status": "error",
        "error": str(exc)[:1000],
        "error_type": type(exc).__name__,
    }


def _compact_source_result(result: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in result.items():
        if key == "results":
            compact["result_count"] = len(value) if isinstance(value, list) else None
            continue
        if key == "errors" and isinstance(value, list):
            compact["error_count"] = len(value)
            compact["errors"] = value[:10]
            continue
        if key in {
            "history",
            "buybacks",
            "recovery",
            "finalization",
            "coverage_result",
            "cash_sync",
            "ir",
            "result_release",
            "consensus",
            "xp_preview",
        } and isinstance(value, dict):
            compact[key] = _compact_source_result(value)
            continue
        compact[key] = value
    return compact


async def start_full_refresh(database: Any, *, target_date: str, trigger: str) -> int:
    repository = PerformanceD1WriteRepository(database)
    return await repository.start_job(
        job_name=JOB_NAME,
        started_at=_now_iso(),
        metadata={"phase": PHASE, "trigger": trigger, "target_date": target_date},
    )


async def refresh_nav(database: Any, *, target_date: str) -> dict[str, Any]:
    repository = PerformanceD1WriteRepository(database)
    result = await refresh_dirty_nav_layers(repository, target_date=target_date)
    return {**result, "repository": repository.performance_metrics()}


async def preflight(database: Any, *, target_date: str) -> dict[str, Any]:
    repository = PerformanceD1WriteRepository(database)
    result = await run_d1_preflight(repository, target_date=target_date)
    return {**result, "repository": repository.performance_metrics()}


def _source_health_status(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "").lower()
    if status in {"ok", "skipped", "success"}:
        return "OK"
    if status in {"partial", "not_available", "no_trade", "review_required"}:
        return "DEGRADED"
    return "DOWN"


def _records_written(results: dict[str, Any], nav: dict[str, Any]) -> int:
    total = 0
    ecb = results.get("ecb") or {}
    total += int(ecb.get("rows_written") or 0)
    if (results.get("b3") or {}).get("status") == "ok":
        total += 1
    total += int((results.get("cvm") or {}).get("archived") or 0)
    total += int((results.get("bemobi_web") or {}).get("rows_written") or 0)
    newsweb = results.get("newsweb") or {}
    total += int((newsweb.get("history") or {}).get("archived") or 0)
    total += int((newsweb.get("buybacks") or {}).get("ingested") or 0)
    attachments = results.get("newsweb_attachments") or {}
    total += int(attachments.get("daily_rows_written") or 0)
    total += int((results.get("otello_reports") or {}).get("applied") or 0)
    otec = results.get("otec_recovery") or {}
    if otec.get("recovery_used") and otec.get("status") == "ok":
        total += 1
    total += len(nav.get("dirty_layers") or [])
    return total


async def finish_full_refresh(
    database: Any,
    *,
    job_id: int,
    target_date: str,
    source_results: dict[str, dict[str, Any]],
    nav_result: dict[str, Any],
    preflight_result: dict[str, Any],
    archive_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = PerformanceD1WriteRepository(database)
    errors: list[dict[str, str]] = []
    compact_sources = {
        name: _compact_source_result(result) for name, result in source_results.items()
    }

    for step_name, result in source_results.items():
        source_code = _SOURCE_CODE_BY_STEP.get(step_name)
        if source_code is None:
            continue
        health = _source_health_status(result)
        detail = str(result.get("error") or "")[:1000] or None
        if step_name == "otello_reports" and int(result.get("review_required") or 0) > 0:
            detail = (
                f"{result.get('review_required')} report message(s) require review; "
                "existing production anchors were retained"
            )
        if step_name == "bemobi_web" and health == "DEGRADED":
            detail = "En eller flere sekundære Bemobi-nettkilder var utilgjengelige; siste gode fakta ble beholdt."
        source_id = await repository.source_id(source_code)
        await repository.run(
            """
            INSERT INTO source_health(
                source_id, checked_at, status, latency_ms, error_message, metadata_json
            ) VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (
                source_id,
                _now_iso(),
                health,
                detail,
                json.dumps(
                    {
                        "phase": PHASE,
                        "target_date": target_date,
                        "result": compact_sources[step_name],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
            ),
        )
        if health == "DOWN":
            errors.append({"step": step_name, "error": detail or "source step failed"})

    if nav_result.get("status") in {"partial", "error"}:
        errors.append({"step": "nav", "error": f"NAV status={nav_result.get('status')}"})
    if not preflight_result.get("ready"):
        errors.append(
            {
                "step": "preflight",
                "error": f"{len(preflight_result.get('blockers') or [])} blocker(s)",
            }
        )
    archive_result = archive_result or {"status": "skipped", "reason": "not_requested"}
    if str(archive_result.get("status") or "").lower() == "error":
        errors.append(
            {
                "step": "r2_snapshot",
                "error": str(archive_result.get("error") or "snapshot failed")[:1000],
            }
        )

    tracked_results = [
        source_results[name]
        for name in _SOURCE_CODE_BY_STEP
        if name in source_results
    ]
    failed_sources = sum(
        1 for result in tracked_results if _source_health_status(result) == "DOWN"
    )
    if (
        tracked_results
        and failed_sources == len(tracked_results)
        and not preflight_result.get("ready")
    ):
        status = "FAILED"
    elif errors or any(
        _source_health_status(result) == "DEGRADED" for result in tracked_results
    ):
        status = "PARTIAL"
    else:
        status = "SUCCESS"

    records_written = _records_written(source_results, nav_result)
    metadata = {
        "phase": PHASE,
        "target_date": target_date,
        "sources": compact_sources,
        "nav": _compact_source_result(nav_result),
        "preflight": {
            "status": preflight_result.get("status"),
            "ready": preflight_result.get("ready"),
            "blockers": preflight_result.get("blockers"),
            "warnings": preflight_result.get("warnings"),
        },
        "archive": _compact_source_result(archive_result),
        "repository": repository.performance_metrics(),
    }
    await repository.finish_job(
        job_id,
        finished_at=_now_iso(),
        status=status,
        records_written=records_written,
        error_message="; ".join(item["error"] for item in errors)[:4000] or None,
        metadata=metadata,
    )
    return {
        "status": status,
        "job_id": job_id,
        "target_date": target_date,
        "records_written": records_written,
        "source_results": source_results,
        "nav": nav_result,
        "preflight": preflight_result,
        "archive": archive_result,
        "errors": errors,
    }

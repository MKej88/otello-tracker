"""Aktiv Bemobi web-orkestrering for Cloudflare Full Workflow.

Offisiell Bemobi IR oppdateres daglig. Tyngre sekundærkilder roteres mellom
resultatdokumenter og offentlige XP-previews. Årsmodeller kommer fra
kildeverifisert offentlig meglerresearch og hentes ikke fra anonyme aggregatorer.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Awaitable, Callable

from bemobi_cvm_post_result import refresh_cvm_financials_after_new_result
from bemobi_ir_refresh import sync_bemobi_ir
from bemobi_web_refresh import (
    BEMOBI_ANALYST_URL,
    BEMOBI_OWNERSHIP_URL,
    sync_latest_result_release,
    sync_xp_preview,
)

_SECONDARY_REFRESH_SLOTS = ("result_release", "xp_preview")


def _secondary_refresh_slot(target_date: str) -> str:
    """Spread CPU-heavier secondary web sources deterministically across nights."""
    ordinal = date.fromisoformat(target_date).toordinal()
    return _SECONDARY_REFRESH_SLOTS[ordinal % len(_SECONDARY_REFRESH_SLOTS)]


def _scheduled_skip(slot: str, active_slot: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "reason": "rotating_cpu_budget",
        "slot": slot,
        "active_slot": active_slot,
        "rows_written": 0,
    }


def _broker_models_status() -> dict[str, Any]:
    """Broker models are source-specific facts, not a nightly scraped aggregate."""
    return {
        "status": "skipped",
        "reason": "source_specific_public_broker_models",
        "rows_written": 0,
    }


def _ir_fetcher_with_url_context(
    fetcher: Callable[..., Awaitable[Any]] | None,
) -> Callable[..., Awaitable[Any]]:
    """Add the exact Bemobi IR URL to transport/HTTP failures for diagnostics."""

    async def wrapped(url: str, **kwargs):
        try:
            if fetcher is None:
                from workers import fetch as workers_fetch

                response = await workers_fetch(url, **kwargs)
            else:
                response = await fetcher(url, **kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"Bemobi IR fetch feilet for {url}: {type(exc).__name__}: {exc}"
            ) from exc

        status = int(getattr(response, "status", 0) or 0)
        if not bool(getattr(response, "ok", False)):
            raise RuntimeError(
                f"Bemobi IR fetch feilet for {url}: HTTP {status or 'unknown'}"
            )
        return response

    return wrapped


def _ir_failed_url(exc: Exception) -> str | None:
    """Resolve a useful source URL also for parser failures raised after a successful fetch."""
    text = str(exc)
    if BEMOBI_OWNERSHIP_URL in text:
        return BEMOBI_OWNERSHIP_URL
    if BEMOBI_ANALYST_URL in text:
        return BEMOBI_ANALYST_URL

    lowered = text.lower()
    if "eier" in lowered or "ownership" in lowered:
        return BEMOBI_OWNERSHIP_URL
    if "analyt" in lowered:
        return BEMOBI_ANALYST_URL
    return None


async def _ensure_consensus_event(
    repository,
    *,
    result_refresh: dict[str, Any],
    target_date: str,
) -> int:
    """Create a data-backed history shell for a newly ingested result, without inventing broker data."""
    if result_refresh.get("status") != "ok" or not result_refresh.get("period"):
        return 0
    period = str(result_refresh["period"])
    existing = await repository.first(
        "SELECT id FROM bemobi_consensus_events WHERE period=? LIMIT 1",
        (period,),
    )
    if existing is not None:
        return 0

    fact = await repository.first(
        """
        SELECT published_date, source_name, source_url, source_document_id
        FROM bemobi_investor_facts
        WHERE fact_type='RESULT' AND fact_key=?
        LIMIT 1
        """,
        (period,),
    )
    if fact is None or not fact.get("published_date"):
        return 0

    model_revision = {
        "status": "WAITING_FOR_PUBLIC_POST_REPORT_MODEL",
        "broker": "XP",
        "before_date": None,
        "after_date": None,
        "target_before_brl": None,
        "target_after_brl": None,
        "source_url": fact.get("source_url"),
        "checked_date": target_date,
        "note": (
            "Ny rapport er registrert. Trackeren venter på en kildeverifisert offentlig "
            "etterrapport-modell før kursmål eller estimatrevisjon fylles inn."
        ),
        "estimate_revisions": [],
    }
    await repository.run(
        """
        INSERT INTO bemobi_consensus_events(
            period, result_date, result_source, result_source_url,
            model_revision_json, quality, notes, source_document_id
        ) VALUES (?, ?, ?, ?, ?, 'AUTO_RESULT_HISTORY', ?, ?)
        """,
        (
            period,
            str(fact["published_date"])[:10],
            str(fact.get("source_name") or "Bemobi/CVM"),
            fact.get("source_url"),
            json.dumps(
                model_revision,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "Opprettet automatisk fra kildebelagt RESULT-faktum; brokerrevisjon fylles ikke uten kilde.",
            fact.get("source_document_id"),
        ),
    )
    return 1


async def refresh_bemobi_web(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh core Bemobi IR and source-specific public broker material."""
    ir_failed = False
    try:
        ir = await sync_bemobi_ir(
            repository,
            target_date=target_date,
            archive_bucket=archive_bucket,
            fetcher=_ir_fetcher_with_url_context(fetcher),
        )
    except Exception as exc:
        ir_failed = True
        ir = {
            "status": "not_available",
            "reason": "official_ir_refresh_failed",
            "error": str(exc)[:700],
            "error_type": type(exc).__name__,
            "failed_url": _ir_failed_url(exc),
            "last_good_preserved": True,
            "rows_written": 0,
        }

    analyst_coverage = (
        ir.get("analyst_coverage")
        if isinstance(ir.get("analyst_coverage"), dict)
        else {}
    )
    best_effort_warnings: list[dict[str, Any]] = []
    if analyst_coverage.get("status") == "not_available":
        best_effort_warnings.append(
            {
                "source": "analyst_coverage",
                "status": "not_available",
                "reason": analyst_coverage.get("reason"),
                "error": analyst_coverage.get("error"),
                "failed_url": analyst_coverage.get("failed_url"),
            }
        )

    active_slot = _secondary_refresh_slot(target_date)
    result: dict[str, Any] = _scheduled_skip("result_release", active_slot)
    broker_models = _broker_models_status()
    xp: dict[str, Any] = _scheduled_skip("xp_preview", active_slot)
    post_result_cvm: dict[str, Any] = {
        "status": "skipped",
        "reason": "no_new_result",
        "rows_written": 0,
    }
    event_rows = 0

    if active_slot == "result_release":
        result = await sync_latest_result_release(
            repository,
            target_date=target_date,
            archive_bucket=archive_bucket,
            fetcher=fetcher,
        )
        event_rows = await _ensure_consensus_event(
            repository,
            result_refresh=result,
            target_date=target_date,
        )
        if event_rows:
            result = {**result, "consensus_event_rows_written": event_rows}
        if result.get("status") == "ok" and result.get("period"):
            if fetcher is None:
                try:
                    post_result_cvm = await refresh_cvm_financials_after_new_result(
                        repository,
                        target_date=target_date,
                        period=str(result["period"]),
                    )
                except Exception as exc:
                    post_result_cvm = {
                        "status": "error",
                        "reason": "post_result_cvm_refresh_failed",
                        "error": str(exc)[:700],
                        "rows_written": 0,
                    }
            else:
                post_result_cvm = {
                    "status": "skipped",
                    "reason": "custom_web_fetcher",
                    "rows_written": 0,
                }
    else:
        xp = await sync_xp_preview(
            repository,
            target_date=target_date,
            archive_bucket=archive_bucket,
            fetcher=fetcher,
        )

    secondary_warnings = [
        {
            "source": name,
            "status": str(item.get("status") or "unknown"),
            "reason": item.get("reason"),
            "error": item.get("error"),
        }
        for name, item in (("result_release", result), ("xp_preview", xp))
        if item.get("status") == "not_available"
    ]
    if post_result_cvm.get("status") in {"error", "partial"}:
        best_effort_warnings.append(
            {
                "source": "post_result_cvm_financials",
                "status": str(post_result_cvm.get("status")),
                "reason": post_result_cvm.get("reason"),
                "error": post_result_cvm.get("error"),
            }
        )

    result_release_degraded = result.get("status") == "not_available"
    non_blocking_degraded = ir_failed and not result_release_degraded
    rows_written = (
        sum(int(item.get("rows_written") or 0) for item in (ir, result, xp))
        + event_rows
        + int(post_result_cvm.get("rows_written") or 0)
    )
    return {
        "status": "partial" if (ir_failed or result_release_degraded) else "ok",
        "rows_written": rows_written,
        "ir": ir,
        "result_release": result,
        "post_result_cvm_financials": post_result_cvm,
        "consensus": broker_models,
        "broker_models": broker_models,
        "xp_preview": xp,
        "secondary_status": "degraded" if secondary_warnings else "ok",
        "secondary_warnings": secondary_warnings,
        "best_effort_status": "degraded" if best_effort_warnings else "ok",
        "best_effort_warnings": best_effort_warnings,
        "non_blocking_degraded": non_blocking_degraded,
        "active_secondary_slot": active_slot,
        "secondary_refresh_max_delay_days": len(_SECONDARY_REFRESH_SLOTS) - 1,
        "policy": "ownership-core-analyst-best-effort-result-release-health-public-broker-models-xp-last-good-preserved",
    }

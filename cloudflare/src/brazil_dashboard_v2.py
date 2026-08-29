from __future__ import annotations

from typing import Any, Awaitable, Callable

import brazil_dashboard as base
from brazil_calendar_expectations import enrich_calendar_expectations
from brazil_focus_resilience import (
    apply_cached_event_expectations,
    persist_event_expectations,
    resolve_annual_focus,
)

# Bruk sesongjustert IBC-Br tjenester når vi viser måned-til-måned-endring.
# 29605 er ujustert nivå; 29606 er samme tjenestekomponent med sesongjustering.
base.SERIES["ibc_services"]["code"] = 29606

_EXTERNAL_CONSENSUS_KINDS = {"services", "retail", "activity"}
_FOCUS_EVENT_KINDS = {"copom", "inflation", "gdp", "labor"}


def _annotate_market_consensus(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe what kind of market expectation is available for each event.

    BCB Focus is a survey of banks and other market participants. For PMS, PMC and
    IBC-Br there is also economist/bank consensus in commercial poll feeds such as
    Reuters/LSEG and Trading Economics, but no equivalent free BCB Focus event series
    is ingested by the tracker. Make that distinction explicit instead of claiming
    that market consensus does not exist.
    """
    annotated: list[dict[str, Any]] = []
    for raw in events:
        event = dict(raw)
        expectation = event.get("expectation")
        if isinstance(expectation, dict) and expectation.get("event_consensus"):
            fallback_cached = bool(expectation.get("fallback_cached"))
            event["market_consensus"] = {
                "available": True,
                "ingested": True,
                "coverage": "BCB_FOCUS_EVENT_CACHED" if fallback_cached else "BCB_FOCUS_EVENT",
                "provider": str(expectation.get("provider") or "BCB Focus"),
                "note": (
                    "Sist gode hendelsesnære Focus-median fra banker, forvaltere og andre "
                    "markedsaktører; live Olinda-data var ikke tilgjengelig."
                    if fallback_cached
                    else "Median fra banker, forvaltere og andre markedsaktører i BCB Focus, "
                    "koblet til denne referanseperioden/hendelsen."
                ),
            }
        elif str(event.get("kind") or "") in _EXTERNAL_CONSENSUS_KINDS:
            event["market_consensus"] = {
                "available": True,
                "ingested": False,
                "coverage": "EXTERNAL_MARKET_CONSENSUS_NOT_INGESTED",
                "provider": None,
                "note": (
                    "Markedskonsensus fra banker/økonomer finnes hos blant annet "
                    "Reuters/LSEG og Trading Economics, men ikke via en gratis BCB Focus-serie "
                    "som trackeren kan hente automatisk."
                ),
            }
        elif str(event.get("kind") or "") in _FOCUS_EVENT_KINDS:
            event["market_consensus"] = {
                "available": True,
                "ingested": False,
                "coverage": "BCB_FOCUS_EVENT_TEMPORARILY_UNAVAILABLE",
                "provider": "BCB Focus",
                "note": (
                    "Denne hendelsestypen dekkes av BCB Focus, men en hendelsesnær verdi "
                    "var ikke tilgjengelig i siste API-kall eller i siste gode cache."
                ),
            }
        else:
            event["market_consensus"] = {
                "available": False,
                "ingested": False,
                "coverage": "NOT_AVAILABLE_IN_CURRENT_FREE_FEEDS",
                "provider": None,
                "note": "Ingen relevant forventningsserie er koblet til denne hendelsen ennå.",
            }
        annotated.append(event)
    return annotated


def _recompute_focus_signals(result: dict[str, Any], focus_values: dict[str, Any], target_year: int) -> None:
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        return
    for key, metric in metrics.items():
        if isinstance(metric, dict):
            metric["signal"] = base._metric_signal(str(key), metric, focus_values, target_year)


async def brazil_dashboard(
    repository,
    *,
    as_of_date: str | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    result = await base.brazil_dashboard(
        repository,
        as_of_date=as_of_date,
        fetcher=fetcher,
    )
    target_date = str(result.get("as_of_date") or as_of_date or "")
    if not target_date:
        return result

    # Annual Focus expectations power the "Hva markedet venter" table. Olinda has
    # proved less reliable than the BCB SGS endpoints, so keep a last-good D1 snapshot
    # and a published Focus bootstrap instead of blanking the whole table on an outage.
    try:
        source_status = result.setdefault("source_status", {})
        live_status = source_status.get("focus") if isinstance(source_status.get("focus"), dict) else {}
        focus, resilience_status = await resolve_annual_focus(
            repository,
            result.get("focus"),
            as_of_date=target_date,
        )
        resilience_status["live_ready"] = bool(live_status.get("ready"))
        if live_status.get("error"):
            resilience_status["live_error"] = live_status.get("error")
        result["focus"] = focus
        source_status["focus"] = resilience_status
        focus_values = focus.get("values") if isinstance(focus.get("values"), dict) else {}
        _recompute_focus_signals(result, focus_values, int(target_date[:4]))
    except Exception as exc:
        result.setdefault("source_status", {})["focus_resilience"] = {
            "ready": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    calendar = result.get("calendar") or []
    if not isinstance(calendar, list) or not calendar:
        return result

    calendar_rows = [dict(item) for item in calendar if isinstance(item, dict)]
    try:
        enriched, status = await enrich_calendar_expectations(
            calendar_rows,
            as_of_date=target_date,
            fetcher=fetcher,
        )
        if status.get("specific_expectations"):
            await persist_event_expectations(repository, enriched)
        enriched, restored = await apply_cached_event_expectations(
            repository,
            enriched,
            as_of_date=target_date,
        )
        status["cached_restored"] = restored
        status["fallback"] = bool(restored and not status.get("ready"))
        result["calendar"] = _annotate_market_consensus(enriched)
        result.setdefault("source_status", {})["focus_event_expectations"] = status
        if status.get("ready") or restored:
            fallback_note = (
                " Ved midlertidig Olinda-feil brukes siste gode lagrede hendelsesforventning."
                if restored
                else ""
            )
            result["calendar_note"] = (
                "For IPCA/IPCA-15, arbeidsledighet, BNP og Copom brukes hendelsesnære "
                "markedsforventninger fra BCB Focus når tilgjengelig. Focus er medianer fra "
                "banker, forvaltere og andre markedsaktører. For PMS, PMC og IBC-Br finnes "
                "også markedskonsensus fra økonom-/bankpoller, men den er ikke tilgjengelig "
                "via en gratis Focus-serie i dagens automatiske feed."
                f"{fallback_note} Rader merket estimated er en rullerende forhåndsvisning og "
                "må bekreftes i den offisielle kalenderen."
            )
    except Exception as exc:
        restored_rows, restored = await apply_cached_event_expectations(
            repository,
            calendar_rows,
            as_of_date=target_date,
        )
        result["calendar"] = _annotate_market_consensus(restored_rows)
        result.setdefault("source_status", {})["focus_event_expectations"] = {
            "ready": bool(restored),
            "fallback": bool(restored),
            "cached_restored": restored,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return result

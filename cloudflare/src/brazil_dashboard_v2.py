from __future__ import annotations

from typing import Any, Awaitable, Callable

import brazil_dashboard as base
from brazil_calendar_expectations import enrich_calendar_expectations

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
            event["market_consensus"] = {
                "available": True,
                "ingested": True,
                "coverage": "BCB_FOCUS_EVENT",
                "provider": str(expectation.get("provider") or "BCB Focus"),
                "note": (
                    "Median fra banker, forvaltere og andre markedsaktører i BCB Focus, "
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
                    "var ikke tilgjengelig i siste API-kall."
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
    calendar = result.get("calendar") or []
    if not isinstance(calendar, list) or not calendar:
        return result

    target_date = str(result.get("as_of_date") or as_of_date or "")
    if not target_date:
        return result

    try:
        enriched, status = await enrich_calendar_expectations(
            [dict(item) for item in calendar if isinstance(item, dict)],
            as_of_date=target_date,
            fetcher=fetcher,
        )
        result["calendar"] = _annotate_market_consensus(enriched)
        result.setdefault("source_status", {})["focus_event_expectations"] = status
        if status.get("ready"):
            result["calendar_note"] = (
                "For IPCA/IPCA-15, arbeidsledighet, BNP og Copom brukes hendelsesnære "
                "markedsforventninger fra BCB Focus når tilgjengelig. Focus er medianer fra "
                "banker, forvaltere og andre markedsaktører. For PMS, PMC og IBC-Br finnes "
                "også markedskonsensus fra økonom-/bankpoller, men den er ikke tilgjengelig "
                "via en gratis Focus-serie i dagens automatiske feed. Rader merket estimated "
                "er en rullerende forhåndsvisning og må bekreftes i den offisielle kalenderen."
            )
    except Exception as exc:
        result["calendar"] = _annotate_market_consensus(
            [dict(item) for item in calendar if isinstance(item, dict)]
        )
        result.setdefault("source_status", {})["focus_event_expectations"] = {
            "ready": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return result

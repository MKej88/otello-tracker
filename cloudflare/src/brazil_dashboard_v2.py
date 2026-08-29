from __future__ import annotations

from typing import Any, Awaitable, Callable

import brazil_dashboard as base
from brazil_calendar_expectations import enrich_calendar_expectations

# Bruk sesongjustert IBC-Br tjenester når vi viser måned-til-måned-endring.
# 29605 er ujustert nivå; 29606 er samme tjenestekomponent med sesongjustering.
base.SERIES["ibc_services"]["code"] = 29606


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
        result["calendar"] = enriched
        result.setdefault("source_status", {})["focus_event_expectations"] = status
        if status.get("ready"):
            result["calendar_note"] = (
                "For IPCA/IPCA-15, arbeidsledighet, BNP og Copom brukes hendelsesnære "
                "BCB Focus-forventninger når tilgjengelig. Andre hendelser bruker års-/"
                "retningsproxy eller vises uten konsensus. Rader merket estimated er en "
                "rullerende forhåndsvisning og må bekreftes i den offisielle kalenderen."
            )
    except Exception as exc:
        result.setdefault("source_status", {})["focus_event_expectations"] = {
            "ready": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return result

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import brazil_dashboard as base
from brazil_calendar_expectations import enrich_calendar_expectations
from brazil_focus_resilience import (
    apply_cached_event_expectations,
    persist_event_expectations,
    resolve_annual_focus,
)
from brazil_investing_consensus import enrich_calendar_from_investing

# Bruk sesongjustert IBC-Br tjenester når vi viser måned-til-måned-endring.
# 29605 er ujustert nivå; 29606 er samme tjenestekomponent med sesongjustering.
base.SERIES["ibc_services"]["code"] = 29606

_EXTERNAL_CONSENSUS_KINDS = {"services", "retail", "activity"}
_FOCUS_EVENT_KINDS = {"copom", "inflation", "gdp", "labor"}
_LATEST_HIGH_MACRO_STATE_KEY = "brazil.latest_high_macro.v1"


def _annotate_market_consensus(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe what kind of market expectation is available for each event."""
    annotated: list[dict[str, Any]] = []
    for raw in events:
        event = dict(raw)
        expectation = event.get("expectation")
        if isinstance(expectation, dict) and expectation.get("event_consensus"):
            fallback_cached = bool(expectation.get("fallback_cached"))
            provider = str(expectation.get("provider") or "BCB Focus")
            if provider == "Investing.com":
                event["market_consensus"] = {
                    "available": True,
                    "ingested": True,
                    "coverage": "INVESTING_EVENT_CACHED" if fallback_cached else "INVESTING_EVENT",
                    "provider": provider,
                    "note": (
                        "Siste gode hendelseskonsensus fra Investing.com-cache; live-kilden var ikke "
                        "tilgjengelig i denne hentingen."
                        if fallback_cached
                        else "Hendelsesnær markedskonsensus fra Investing.com sitt Forecast-felt."
                    ),
                }
            else:
                event["market_consensus"] = {
                    "available": True,
                    "ingested": True,
                    "coverage": "BCB_FOCUS_EVENT_CACHED" if fallback_cached else "BCB_FOCUS_EVENT",
                    "provider": provider,
                    "note": (
                        "Sist gode hendelsesnære Focus-median fra banker, forvaltere og andre "
                        "markedsaktører; live Olinda-data var ikke tilgjengelig."
                        if fallback_cached
                        else "Median fra banker, forvaltere og andre markedsaktører i BCB Focus, "
                        "koblet til denne referanseperioden/hendelsen."
                    ),
                }
        elif isinstance(expectation, dict) and expectation.get("value") is not None:
            # Et årsestimat kan være nyttig kontekst, men det er ikke konsensus for
            # den konkrete makropubliseringen og skal aldri presenteres som det.
            event["market_consensus"] = {
                "available": True,
                "ingested": True,
                "coverage": "BCB_FOCUS_ANNUAL_PROXY",
                "provider": "BCB Focus",
                "note": (
                    "Et årsestimat fra BCB Focus finnes som bakgrunn, men brukes ikke som "
                    "hendelseskonsensus for denne publiseringen."
                ),
            }
        elif str(event.get("kind") or "") in _EXTERNAL_CONSENSUS_KINDS:
            event["market_consensus"] = {
                "available": True,
                "ingested": False,
                "coverage": "EXTERNAL_MARKET_CONSENSUS_NOT_INGESTED",
                "provider": "Investing.com",
                "note": (
                    "Trackeren forsøker å hente hendelseskonsensus fra Investing.com, men et "
                    "gyldig Forecast-tall var ikke tilgjengelig for denne publiseringen nå."
                ),
            }
        elif str(event.get("kind") or "") in _FOCUS_EVENT_KINDS:
            event["market_consensus"] = {
                "available": True,
                "ingested": False,
                "coverage": "EVENT_CONSENSUS_TEMPORARILY_UNAVAILABLE",
                "provider": None,
                "note": (
                    "Ingen hendelsesnær konsensus fra Investing.com eller BCB Focus var "
                    "tilgjengelig i siste hentning eller i siste gode cache."
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


def _fill_annual_focus_proxies(
    events: list[dict[str, Any]], focus_values: dict[str, Any]
) -> list[dict[str, Any]]:
    """Fyll tomme kalenderfelt fra den robuste, årlige Focus-reserven."""
    output: list[dict[str, Any]] = []
    for raw in events:
        event = dict(raw)
        if not isinstance(event.get("expectation"), dict):
            event_date = str(event.get("date") or "")
            if len(event_date) >= 4 and event_date[:4].isdigit():
                event["expectation"] = base._focus_expectation_for_event(
                    event,
                    focus_values,
                    int(event_date[:4]),
                )
        output.append(event)
    return output


def _recompute_focus_signals(result: dict[str, Any], focus_values: dict[str, Any], target_year: int) -> None:
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        return
    for key, metric in metrics.items():
        if isinstance(metric, dict):
            metric["signal"] = base._metric_signal(str(key), metric, focus_values, target_year)


def _append_investing_source(result: dict[str, Any]) -> None:
    sources = result.get("sources")
    if not isinstance(sources, list):
        sources = []
        result["sources"] = sources
    if any(isinstance(item, dict) and item.get("name") == "Investing.com" for item in sources):
        return
    sources.append(
        {
            "name": "Investing.com",
            "url": "https://www.investing.com/economic-calendar/",
        }
    )


async def _load_latest_high_macro(repository) -> dict[str, Any] | None:
    row = await repository.first(
        "SELECT value FROM runtime_state WHERE key=? LIMIT 1",
        (_LATEST_HIGH_MACRO_STATE_KEY,),
    )
    if row is None:
        return None
    try:
        payload = json.loads(str(row.get("value") or ""))
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def _resolve_latest_high_macro(
    repository,
    candidate: dict[str, Any] | None,
    *,
    as_of_date: str,
) -> dict[str, Any] | None:
    """Keep the newest exact-Høy release visible until a newer one is observed."""
    existing = await _load_latest_high_macro(repository)
    existing_date = str((existing or {}).get("date") or "")
    candidate_date = str((candidate or {}).get("date") or "")

    if candidate is not None and candidate_date:
        if existing_date and existing_date > candidate_date:
            return existing if existing_date <= as_of_date else candidate
        await repository.run(
            """
            INSERT INTO runtime_state(key, value, updated_at)
            VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (
                _LATEST_HIGH_MACRO_STATE_KEY,
                json.dumps(candidate, ensure_ascii=False, sort_keys=True),
            ),
        )
        return candidate

    if existing is not None and existing_date and existing_date <= as_of_date:
        return existing
    return None


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

    focus = result.get("focus")
    focus_values = focus.get("values") if isinstance(focus, dict) else {}
    if not isinstance(focus_values, dict):
        focus_values = {}
    calendar_rows = _fill_annual_focus_proxies(
        [dict(item) for item in calendar if isinstance(item, dict)],
        focus_values,
    )
    latest_candidate: dict[str, Any] | None = None
    try:
        enriched, status = await enrich_calendar_expectations(
            calendar_rows,
            as_of_date=target_date,
            fetcher=fetcher,
        )

        try:
            enriched, investing_status = await enrich_calendar_from_investing(
                enriched,
                as_of_date=target_date,
                fetcher=fetcher,
            )
            candidate = investing_status.pop("latest_high_importance_release", None)
            if isinstance(candidate, dict):
                latest_candidate = candidate
        except Exception as exc:
            investing_status = {
                "ready": False,
                "source": "Investing.com",
                "error": f"{type(exc).__name__}: {exc}",
            }

        try:
            # Persist only true event consensus. Investing enrichment includes the
            # release time in that object, so a last-good consensus also carries time.
            await persist_event_expectations(repository, enriched)
        except Exception as exc:
            # Cache writes are best-effort: a transient D1 failure must not discard
            # live values that were already fetched successfully.
            status["cache_persistence_error"] = f"{type(exc).__name__}: {exc}"

        try:
            enriched, restored = await apply_cached_event_expectations(
                repository,
                enriched,
                as_of_date=target_date,
            )
        except Exception as exc:
            restored = 0
            status["cache_restore_error"] = f"{type(exc).__name__}: {exc}"

        status["cached_restored"] = restored
        status["fallback"] = bool(restored and not status.get("ready") and not investing_status.get("ready"))
        result["calendar"] = _annotate_market_consensus(enriched)
        result.setdefault("source_status", {})["focus_event_expectations"] = status
        result.setdefault("source_status", {})["investing_event_expectations"] = investing_status
        if investing_status.get("pages_ready"):
            _append_investing_source(result)

        fallback_note = (
            " Ved midlertidig kildefeil brukes siste gode lagrede hendelseskonsensus."
            if restored
            else ""
        )
        result["calendar_note"] = (
            "Bekreftede publiseringsdatoer kommer fra IBGE/BCB. Publiseringstid og "
            "hendelsesnær markedskonsensus hentes fra Investing.com når tilgjengelig; "
            "tidspunktet konverteres til norsk tid i nettleseren. BCB Focus brukes som "
            "sekundær hendelsesforventning der en relevant serie finnes. Årlige Focus-tall "
            "brukes ikke som konsensus for en konkret publisering."
            f"{fallback_note} Rader merket estimated er en rullerende forhåndsvisning og "
            "må bekreftes i den offisielle kalenderen."
        )
    except Exception as exc:
        try:
            restored_rows, restored = await apply_cached_event_expectations(
                repository,
                calendar_rows,
                as_of_date=target_date,
            )
            restore_error = None
        except Exception as restore_exc:
            # Never repeat a failing cache read out of protection and turn a usable
            # base calendar into a dashboard 500.
            restored_rows, restored = calendar_rows, 0
            restore_error = f"{type(restore_exc).__name__}: {restore_exc}"
        result["calendar"] = _annotate_market_consensus(restored_rows)
        fallback_status = {
            "ready": bool(restored),
            "fallback": bool(restored),
            "cached_restored": restored,
            "error": f"{type(exc).__name__}: {exc}",
        }
        if restore_error:
            fallback_status["cache_restore_error"] = restore_error
        result.setdefault("source_status", {})["focus_event_expectations"] = fallback_status

    try:
        latest_release = await _resolve_latest_high_macro(
            repository,
            latest_candidate,
            as_of_date=target_date,
        )
        result["latest_high_importance_release"] = latest_release
        result.setdefault("source_status", {})["latest_high_macro"] = {
            "ready": latest_release is not None,
            "source": "Investing.com",
            "persisted": latest_release is not None and latest_candidate is None,
        }
    except Exception as exc:
        result.setdefault("source_status", {})["latest_high_macro"] = {
            "ready": False,
            "source": "Investing.com",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return result

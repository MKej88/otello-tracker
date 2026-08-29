from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

ANNUAL_STATE_KEY = "brazil_focus_annual_v1"
EVENT_STATE_KEY = "brazil_focus_event_expectations_v1"
BOOTSTRAP_REFERENCE_DATE = "2026-08-21"
BOOTSTRAP_PUBLICATION_DATE = "2026-08-24"
BOOTSTRAP_SOURCE_URL = "https://www.bcb.gov.br/publicacoes/focus/21082026"

# Emergency bootstrap from the latest published BCB Focus report available when this
# fallback was introduced. It is only used if Olinda is unavailable and no newer
# last-good snapshot has ever been persisted. A successful Olinda response immediately
# supersedes this seed.
_BOOTSTRAP_VALUES: dict[str, dict[str, dict[str, Any]]] = {
    "selic": {
        "2026": {"median": 13.75, "survey_date": BOOTSTRAP_REFERENCE_DATE},
        "2027": {"median": 12.00, "survey_date": BOOTSTRAP_REFERENCE_DATE},
    },
    "ipca": {
        "2026": {"median": 5.02, "survey_date": BOOTSTRAP_REFERENCE_DATE},
        "2027": {"median": 4.25, "survey_date": BOOTSTRAP_REFERENCE_DATE},
    },
    "gdp": {
        "2026": {"median": 1.95, "survey_date": BOOTSTRAP_REFERENCE_DATE},
        "2027": {"median": 1.50, "survey_date": BOOTSTRAP_REFERENCE_DATE},
    },
    "usd_brl": {
        "2026": {"median": 5.20, "survey_date": BOOTSTRAP_REFERENCE_DATE},
        "2027": {"median": 5.30, "survey_date": BOOTSTRAP_REFERENCE_DATE},
    },
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _latest_survey_date(values: Any) -> str | None:
    if not isinstance(values, dict):
        return None
    dates: list[str] = []
    for by_year in values.values():
        if not isinstance(by_year, dict):
            continue
        for point in by_year.values():
            if not isinstance(point, dict):
                continue
            value = str(point.get("survey_date") or "")[:10]
            if value:
                dates.append(value)
    return max(dates) if dates else None


def _valid_values(values: Any) -> bool:
    if not isinstance(values, dict) or not values:
        return False
    return any(
        isinstance(by_year, dict)
        and any(isinstance(point, dict) and point.get("median") is not None for point in by_year.values())
        for by_year in values.values()
    )


def _merge_missing_annual_values(
    live_values: dict[str, Any],
    cached_values: Any,
    *,
    as_of_date: str,
) -> dict[str, Any]:
    """Fill gaps in a live response without replacing any live point."""
    merged: dict[str, Any] = {}
    if isinstance(cached_values, dict):
        for indicator, by_year in cached_values.items():
            if not isinstance(by_year, dict):
                continue
            eligible = {
                str(year): dict(point)
                for year, point in by_year.items()
                if isinstance(point, dict)
                and point.get("median") is not None
                and (
                    not str(point.get("survey_date") or "")[:10]
                    or str(point.get("survey_date") or "")[:10] <= as_of_date
                )
            }
            if eligible:
                merged[str(indicator)] = eligible

    for indicator, by_year in live_values.items():
        if not isinstance(by_year, dict):
            continue
        target = merged.setdefault(str(indicator), {})
        for year, point in by_year.items():
            # Live data is authoritative, including any extra metadata attached
            # to a point, so cached completion can never overwrite it.
            target[str(year)] = dict(point) if isinstance(point, dict) else point
    return merged


async def _read_state(repository: Any, key: str) -> dict[str, Any] | None:
    row = await repository.first(
        "SELECT value, updated_at FROM runtime_state WHERE key = ?",
        (key,),
    )
    if row is None:
        return None
    try:
        payload = json.loads(str(row.get("value") or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    payload.setdefault("cached_at", row.get("updated_at"))
    return payload


async def _write_annual_point(
    repository: Any,
    indicator: str,
    year: str,
    point: dict[str, Any],
    *,
    source: str,
    source_url: str | None,
) -> None:
    """Atomically merge one annual point unless the cache has a newer survey."""
    updated_at = _now_iso()
    survey_date = str(point.get("survey_date") or "")[:10]
    payload = {
        "values": {indicator: {year: point}},
        "source": source,
        "source_url": source_url,
        "survey_date": survey_date,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    await repository.run(
        """
        INSERT INTO runtime_state(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = json_patch(runtime_state.value, excluded.value),
            updated_at = excluded.updated_at
        WHERE COALESCE(
                  json_extract(runtime_state.value, '$.values.' || json_quote(?) || '.'
                               || json_quote(?) || '.survey_date'),
                  ''
              ) <= ?
        """,
        (ANNUAL_STATE_KEY, encoded, updated_at, indicator, year, survey_date),
    )


async def _write_event_expectation(
    repository: Any,
    key: str,
    expectation: dict[str, Any],
) -> None:
    """Atomically add one event unless the cache already has a newer survey."""
    updated_at = _now_iso()
    payload = {"expectations": {key: expectation}}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    # Each upsert carries exactly one event. This lets SQLite serialize the
    # read/compare/merge at the write boundary while json_patch preserves every
    # unrelated event written by concurrent dashboard requests.
    await repository.run(
        """
        INSERT INTO runtime_state(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = json_patch(runtime_state.value, excluded.value),
            updated_at = excluded.updated_at
        WHERE COALESCE(
                  json_extract(runtime_state.value, '$.expectations.' || json_quote(?) || '.survey_date'),
                  ''
              ) <= COALESCE(
                  json_extract(excluded.value, '$.expectations.' || json_quote(?) || '.survey_date'),
                  ''
              )
        """,
        (EVENT_STATE_KEY, encoded, updated_at, key, key),
    )


async def persist_annual_focus(
    repository: Any,
    focus_payload: dict[str, Any],
    *,
    as_of_date: str,
) -> None:
    values = focus_payload.get("values")
    if not _valid_values(values):
        return

    # Once the report was public, seed every write with its complete coverage.
    # Per-point conflict checks keep this seed from replacing fresher live values,
    # while filling gaps in an empty or previously partial cache.
    batches = []
    if as_of_date >= BOOTSTRAP_PUBLICATION_DATE:
        batches.append((_BOOTSTRAP_VALUES, "Banco Central do Brasil / Focus", BOOTSTRAP_SOURCE_URL))
    batches.append(
        (
            values,
            focus_payload.get("source") or "Banco Central do Brasil / Focus",
            focus_payload.get("source_url"),
        )
    )
    for batch, source, source_url in batches:
        await _persist_annual_points(repository, batch, source=source, source_url=source_url)


async def _persist_annual_points(
    repository: Any,
    values: dict[str, Any],
    *,
    source: str,
    source_url: str | None,
) -> None:
    for indicator, by_year in values.items():
        if not isinstance(by_year, dict):
            continue
        for year, point in by_year.items():
            if not isinstance(point, dict) or point.get("median") is None:
                continue
            await _write_annual_point(
                repository,
                str(indicator),
                str(year),
                dict(point),
                source=source,
                source_url=source_url,
            )


async def resolve_annual_focus(
    repository: Any,
    live_focus: Any,
    *,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(live_focus, dict) and live_focus.get("ready") and _valid_values(live_focus.get("values")):
        await persist_annual_focus(repository, live_focus, as_of_date=as_of_date)
        survey_date = _latest_survey_date(live_focus.get("values"))
        result = dict(live_focus)
        try:
            cached = await _read_state(repository, ANNUAL_STATE_KEY)
        except Exception:  # noqa: BLE001 - cache completion must not hide valid live data
            cached = None
        completion_values = cached.get("values") if cached else None
        if completion_values is None and as_of_date >= BOOTSTRAP_PUBLICATION_DATE:
            completion_values = _BOOTSTRAP_VALUES
        result["values"] = _merge_missing_annual_values(
            live_focus["values"],
            completion_values,
            as_of_date=as_of_date,
        )
        result["fallback"] = False
        result["data_source"] = "BCB_OLINDA_LIVE"
        return result, {"ready": True, "fallback": False, "survey_date": survey_date}

    cached = await _read_state(repository, ANNUAL_STATE_KEY)
    if cached and _valid_values(cached.get("values")):
        survey_date = _latest_survey_date(cached.get("values"))
        if not survey_date or survey_date <= as_of_date:
            result = {
                "ready": True,
                "values": cached["values"],
                "source": cached.get("source") or "Banco Central do Brasil / Focus",
                "source_url": cached.get("source_url"),
                "fallback": True,
                "data_source": "LAST_GOOD_D1_CACHE",
                "cached_at": cached.get("cached_at"),
                "note": (
                    "BCB Olinda svarte ikke. Viser siste gode Focus-data som er lagret i trackeren. "
                    f"Siste måling: {survey_date or 'ukjent'}."
                ),
            }
            return result, {
                "ready": True,
                "fallback": True,
                "fallback_source": "LAST_GOOD_D1_CACHE",
                "survey_date": survey_date,
            }

    # The survey reference date predates publication; historical responses must not
    # expose the report until it was publicly available.
    if as_of_date >= BOOTSTRAP_PUBLICATION_DATE:
        result = {
            "ready": True,
            "values": _BOOTSTRAP_VALUES,
            "source": "Banco Central do Brasil / Focus",
            "source_url": BOOTSTRAP_SOURCE_URL,
            "fallback": True,
            "data_source": "PUBLISHED_FOCUS_BOOTSTRAP",
            "note": (
                "BCB Olinda svarte ikke og ingen nyere lagret Focus-respons finnes ennå. "
                f"Viser publisert Focus fra {BOOTSTRAP_REFERENCE_DATE} "
                f"(publisert {BOOTSTRAP_PUBLICATION_DATE}) som nød-fallback."
            ),
        }
        return result, {
            "ready": True,
            "fallback": True,
            "fallback_source": "PUBLISHED_FOCUS_BOOTSTRAP",
            "survey_date": BOOTSTRAP_REFERENCE_DATE,
        }

    result = dict(live_focus) if isinstance(live_focus, dict) else {"ready": False, "values": {}}
    return result, {"ready": False, "fallback": False}


def _event_key(event: dict[str, Any]) -> str:
    return "|".join(
        [
            str(event.get("date") or ""),
            str(event.get("name") or ""),
            str(event.get("reference") or ""),
        ]
    )


async def persist_event_expectations(repository: Any, events: list[dict[str, Any]]) -> None:
    for event in events:
        expectation = event.get("expectation")
        if not isinstance(expectation, dict) or not expectation.get("event_consensus"):
            continue
        await _write_event_expectation(repository, _event_key(event), dict(expectation))


async def apply_cached_event_expectations(
    repository: Any,
    events: list[dict[str, Any]],
    *,
    as_of_date: str,
) -> tuple[list[dict[str, Any]], int]:
    cached = await _read_state(repository, EVENT_STATE_KEY)
    stored = cached.get("expectations") if isinstance(cached, dict) else None
    if not isinstance(stored, dict):
        return events, 0
    restored = 0
    output: list[dict[str, Any]] = []
    for raw in events:
        event = dict(raw)
        current = event.get("expectation")
        if isinstance(current, dict) and current.get("event_consensus"):
            output.append(event)
            continue
        expectation = stored.get(_event_key(event))
        survey_date = str(expectation.get("survey_date") or "") if isinstance(expectation, dict) else ""
        if isinstance(expectation, dict) and (not survey_date or survey_date <= as_of_date):
            restored_expectation = dict(expectation)
            restored_expectation["fallback_cached"] = True
            event["expectation"] = restored_expectation
            restored += 1
        output.append(event)
    return output, restored

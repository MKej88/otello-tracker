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


async def _write_state(repository: Any, key: str, payload: dict[str, Any]) -> None:
    updated_at = _now_iso()
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    await repository.run(
        """
        INSERT INTO runtime_state(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, encoded, updated_at),
    )


async def persist_annual_focus(repository: Any, focus_payload: dict[str, Any]) -> None:
    values = focus_payload.get("values")
    if not _valid_values(values):
        return
    survey_date = _latest_survey_date(values)
    existing = await _read_state(repository, ANNUAL_STATE_KEY)
    existing_date = _latest_survey_date((existing or {}).get("values"))
    if existing_date and survey_date and existing_date > survey_date:
        return
    await _write_state(
        repository,
        ANNUAL_STATE_KEY,
        {
            "values": values,
            "source": focus_payload.get("source") or "Banco Central do Brasil / Focus",
            "source_url": focus_payload.get("source_url"),
            "survey_date": survey_date,
        },
    )


async def resolve_annual_focus(
    repository: Any,
    live_focus: Any,
    *,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(live_focus, dict) and live_focus.get("ready") and _valid_values(live_focus.get("values")):
        await persist_annual_focus(repository, live_focus)
        survey_date = _latest_survey_date(live_focus.get("values"))
        result = dict(live_focus)
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

    if as_of_date >= BOOTSTRAP_REFERENCE_DATE:
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
    existing = await _read_state(repository, EVENT_STATE_KEY) or {}
    stored = existing.get("expectations") if isinstance(existing.get("expectations"), dict) else {}
    merged = dict(stored)
    changed = False
    for event in events:
        expectation = event.get("expectation")
        if not isinstance(expectation, dict) or not expectation.get("event_consensus"):
            continue
        key = _event_key(event)
        previous = merged.get(key)
        previous_date = str(previous.get("survey_date") or "") if isinstance(previous, dict) else ""
        survey_date = str(expectation.get("survey_date") or "")
        if previous_date and survey_date and previous_date > survey_date:
            continue
        merged[key] = dict(expectation)
        changed = True
    if changed:
        await _write_state(repository, EVENT_STATE_KEY, {"expectations": merged})


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

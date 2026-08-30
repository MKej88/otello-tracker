from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.db.connection import get_connection


@dataclass(frozen=True)
class _SourceDefinition:
    key: str
    fact_types: tuple[str, ...]
    source_name: str | None
    source_label: str
    label: str


@dataclass(frozen=True)
class _OperationalSourceDefinition:
    key: str
    source_code: str
    source_label: str
    label: str


_OPERATIONAL_SOURCE_DEFINITIONS = (
    _OperationalSourceDefinition(
        "norges_bank", "NORGES_BANK", "Norges Bank", "Valutakurser (BRL/NOK og USD/NOK)"
    ),
    _OperationalSourceDefinition("b3", "B3", "B3", "Bemobi-kurs og markedsdata"),
    _OperationalSourceDefinition(
        "euronext", "EURONEXT", "Euronext / OTEC", "OTEC-kurs og handler"
    ),
    _OperationalSourceDefinition(
        "yahoo_finance",
        "YAHOO_FINANCE",
        "Life360 / Yahoo Finance",
        "Life360-kurs",
    ),
    _OperationalSourceDefinition(
        "newsweb", "NEWSWEB", "NewsWeb", "Børsmeldinger og tilbakekjøp"
    ),
    _OperationalSourceDefinition(
        "otello_ir", "OTELLO_IR", "Otello IR", "Rapporter og selskapsinformasjon"
    ),
    _OperationalSourceDefinition(
        "life360_ir",
        "LIFE360_IR_LSEG",
        "Life360 IR / LSEG",
        "Reservekilde for Life360-kurs",
    ),
)


_SOURCE_DEFINITIONS = (
    _SourceDefinition(
        "ir",
        ("OWNERSHIP", "ANALYST"),
        None,
        "Bemobi IR",
        "Eierandel og analytikerdekning",
    ),
    _SourceDefinition(
        "result_release",
        ("RESULT",),
        None,
        "CVM / Bemobi",
        "Resultater",
    ),
    _SourceDefinition(
        "consensus",
        ("FORWARD_CONSENSUS",),
        None,
        "MarketScreener",
        "Årsestimater / konsensus",
    ),
    _SourceDefinition(
        "xp_preview",
        ("NEXT_QUARTER",),
        "XP",
        "XP",
        "Forhåndsestimat neste kvartal",
    ),
)


def _sub_result(metadata: dict[str, Any], key: str) -> dict[str, Any]:
    result = metadata.get("result")
    if not isinstance(result, dict):
        return {}
    value = result.get(key)
    return value if isinstance(value, dict) else {}


def _display_status(key: str, result: dict[str, Any]) -> tuple[str, str, bool]:
    status = str(result.get("status") or "").lower()
    reason = str(result.get("reason") or "")
    error = str(result.get("error") or "")

    if status in {"ok", "success"}:
        return "OK", "Siste kontroll fullført uten feil.", False
    if status == "skipped":
        if key == "result_release" and reason == "latest_result_already_ingested":
            return (
                "OK",
                "Ingen ny rapport; siste offentlige rapport er allerede innlest.",
                False,
            )
        return "OK", reason.replace("_", " ") or "Ingen ny data å behandle.", False
    if status == "not_available":
        if key == "xp_preview" and reason in {
            "no_public_preview_for_next_quarter",
            "next_quarter_not_initialized",
        }:
            return (
                "WAITING",
                "Ingen offentlig XP-preview funnet for neste kvartal.",
                False,
            )
        return (
            "DEGRADED",
            error or reason.replace("_", " ") or "Kilden var ikke tilgjengelig.",
            True,
        )
    if status == "partial":
        return (
            "DEGRADED",
            "Deler av innhentingen feilet; siste gode data beholdes.",
            True,
        )
    if status in {"error", "failed", "down"}:
        return "ERROR", error or "Kildekontrollen feilet.", True
    return (
        "UNKNOWN",
        "Ingen ny Full Refresh-kontroll er registrert etter aktivering.",
        False,
    )


def _latest_fact(
    connection, fact_types: tuple[str, ...], *, source_name: str | None = None
) -> dict[str, Any] | None:
    placeholders = ",".join("?" for _ in fact_types)
    parameters: list[Any] = list(fact_types)
    source_clause = ""
    if source_name is not None:
        source_clause = " AND source_name = ?"
        parameters.append(source_name)
    row = connection.execute(
        f"""
        SELECT fact_type, fact_key, as_of_date, published_date, source_name, source_url,
               quality, updated_at
        FROM bemobi_investor_facts
        WHERE fact_type IN ({placeholders}){source_clause}
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        tuple(parameters),
    ).fetchone()
    return None if row is None else dict(row)


def _operational_source_items(connection) -> list[dict[str, Any]]:
    source_codes = tuple(
        source.source_code for source in _OPERATIONAL_SOURCE_DEFINITIONS
    )
    placeholders = ",".join("?" for _ in source_codes)
    rows = connection.execute(
        f"""
        SELECT s.code,
               s.base_url,
               sh.checked_at,
               sh.status,
               sh.error_message,
               sd.fetched_at,
               sd.published_at
        FROM sources s
        LEFT JOIN source_health sh ON sh.id = (
            SELECT id FROM source_health
            WHERE source_id = s.id
            ORDER BY checked_at DESC, id DESC
            LIMIT 1
        )
        LEFT JOIN source_documents sd ON sd.id = (
            SELECT id FROM source_documents
            WHERE source_id = s.id
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
        )
        WHERE s.code IN ({placeholders})
        """,
        source_codes,
    ).fetchall()
    values_by_code = {str(row["code"]): dict(row) for row in rows}

    items: list[dict[str, Any]] = []
    for source in _OPERATIONAL_SOURCE_DEFINITIONS:
        values = values_by_code.get(source.source_code, {})
        health_status = str(values.get("status") or "UNKNOWN").upper()
        status = "ERROR" if health_status == "DOWN" else health_status
        detail = values.get("error_message")
        if status == "UNKNOWN":
            detail = "Ingen kildekontroll er registrert ennå."
        elif status == "OK":
            detail = "Siste kontroll fullført uten feil."
        elif not detail:
            detail = "Kilden har et registrert avvik; siste gode data beholdes."
        items.append(
            {
                "key": source.key,
                "label": source.label,
                "source": source.source_label,
                "status": status,
                "checked_at": values.get("checked_at"),
                "last_good_at": values.get("fetched_at"),
                "data_date": values.get("published_at"),
                "quality": None,
                "url": values.get("base_url"),
                "uses_last_good": status in {"DEGRADED", "ERROR"}
                and values.get("fetched_at") is not None,
                "detail": detail,
            }
        )
    return items


def _status_for_connection(connection) -> dict[str, Any]:
    row = connection.execute("""
        SELECT sh.checked_at, sh.status, sh.error_message, sh.metadata_json
        FROM source_health sh
        JOIN sources s ON s.id = sh.source_id
        WHERE s.code = 'BEMOBI_IR'
        ORDER BY sh.checked_at DESC, sh.id DESC
        LIMIT 1
        """).fetchone()
    health = None if row is None else dict(row)
    metadata: dict[str, Any] = {}
    if health is not None:
        try:
            parsed = json.loads(str(health.get("metadata_json") or "{}"))
            if isinstance(parsed, dict):
                metadata = parsed
        except (TypeError, ValueError):
            metadata = {}

    items = _operational_source_items(connection)
    for source in _SOURCE_DEFINITIONS:
        result = _sub_result(metadata, source.key)
        status, detail, uses_last_good = _display_status(source.key, result)
        fact = _latest_fact(
            connection,
            source.fact_types,
            source_name=source.source_name,
        )
        items.append(
            {
                "key": source.key,
                "label": source.label,
                "source": (fact or {}).get("source_name") or source.source_label,
                "status": status,
                "checked_at": None if health is None else health.get("checked_at"),
                "last_good_at": None if fact is None else fact.get("updated_at"),
                "data_date": (
                    None
                    if fact is None
                    else (fact.get("as_of_date") or fact.get("published_date"))
                ),
                "quality": None if fact is None else fact.get("quality"),
                "url": None if fact is None else fact.get("source_url"),
                "uses_last_good": uses_last_good and fact is not None,
                "detail": detail,
            }
        )

    critical = next(item for item in items if item["key"] == "ir")
    if critical["status"] == "ERROR":
        overall = "ERROR"
    elif any(item["status"] in {"ERROR", "DEGRADED"} for item in items):
        overall = "PARTIAL"
    elif health is None or any(item["status"] == "UNKNOWN" for item in items):
        overall = "UNKNOWN"
    else:
        overall = "OK"

    return {
        "overall_status": overall,
        "checked_at": None if health is None else health.get("checked_at"),
        "workflow_status": None if health is None else health.get("status"),
        "items": items,
        "policy": "official-first-last-good-preserved",
    }


def bemobi_source_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        return _status_for_connection(connection)

from __future__ import annotations

import json
from typing import Any


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
            return "OK", "Ingen ny rapport; siste offentlige rapport er allerede innlest.", False
        return "OK", reason.replace("_", " ") or "Ingen ny data å behandle.", False
    if status == "not_available":
        if key == "xp_preview" and reason in {
            "no_public_preview_for_next_quarter",
            "next_quarter_not_initialized",
        }:
            return "WAITING", "Ingen offentlig XP-preview funnet for neste kvartal.", False
        return "DEGRADED", error or reason.replace("_", " ") or "Kilden var ikke tilgjengelig.", True
    if status == "partial":
        return "DEGRADED", "Deler av innhentingen feilet; siste gode data beholdes.", True
    if status in {"error", "failed", "down"}:
        return "ERROR", error or "Kildekontrollen feilet.", True
    return "UNKNOWN", "Ingen ny Full Refresh-kontroll er registrert etter aktivering.", False


async def _latest_fact(repository, fact_types: tuple[str, ...], *, source_name: str | None = None) -> dict[str, Any] | None:
    placeholders = ",".join("?" for _ in fact_types)
    parameters: list[Any] = list(fact_types)
    source_clause = ""
    if source_name is not None:
        source_clause = " AND source_name = ?"
        parameters.append(source_name)
    return await repository.first(
        f"""
        SELECT fact_type, fact_key, as_of_date, published_date, source_name, source_url,
               quality, updated_at
        FROM bemobi_investor_facts
        WHERE fact_type IN ({placeholders}){source_clause}
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        tuple(parameters),
    )


async def bemobi_source_status(repository) -> dict[str, Any]:
    health = await repository.first(
        """
        SELECT sh.checked_at, sh.status, sh.error_message, sh.metadata_json
        FROM source_health sh
        JOIN sources s ON s.id = sh.source_id
        WHERE s.code = 'BEMOBI_IR'
        ORDER BY sh.checked_at DESC, sh.id DESC
        LIMIT 1
        """
    )
    metadata: dict[str, Any] = {}
    if health is not None:
        try:
            parsed = json.loads(str(health.get("metadata_json") or "{}"))
            if isinstance(parsed, dict):
                metadata = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}

    fact_map = {
        "ir": await _latest_fact(repository, ("OWNERSHIP", "ANALYST")),
        "result_release": await _latest_fact(repository, ("RESULT",)),
        "consensus": await _latest_fact(repository, ("FORWARD_CONSENSUS",)),
        "xp_preview": await _latest_fact(repository, ("NEXT_QUARTER",), source_name="XP"),
    }
    labels = {
        "ir": ("Bemobi IR", "Eierandel og analytikerdekning"),
        "result_release": ("CVM / Bemobi", "Resultater"),
        "consensus": ("MarketScreener", "Årsestimater / konsensus"),
        "xp_preview": ("XP", "Forhåndsestimat neste kvartal"),
    }

    items: list[dict[str, Any]] = []
    for key in ("ir", "result_release", "consensus", "xp_preview"):
        result = _sub_result(metadata, key)
        status, detail, uses_last_good = _display_status(key, result)
        fact = fact_map[key]
        source_label, label = labels[key]
        items.append(
            {
                "key": key,
                "label": label,
                "source": (fact or {}).get("source_name") or source_label,
                "status": status,
                "checked_at": None if health is None else health.get("checked_at"),
                "last_good_at": None if fact is None else fact.get("updated_at"),
                "data_date": None if fact is None else (fact.get("as_of_date") or fact.get("published_date")),
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

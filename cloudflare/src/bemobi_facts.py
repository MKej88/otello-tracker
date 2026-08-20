from __future__ import annotations

import json
from typing import Any


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(str(row.get("payload_json") or "{}"))
    if not isinstance(payload, dict):
        raise ValueError(f"Ugyldig Bemobi payload for {row.get('fact_type')}/{row.get('fact_key')}")
    return {
        **payload,
        "_fact_type": row.get("fact_type"),
        "_fact_key": row.get("fact_key"),
        "_as_of_date": row.get("as_of_date"),
        "_published_date": row.get("published_date"),
        "_source_name": row.get("source_name"),
        "_source_url": row.get("source_url"),
        "_quality": row.get("quality"),
        "_notes": row.get("notes"),
    }


async def load_bemobi_facts(repository, fact_type: str) -> list[dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT fact_type, fact_key, as_of_date, published_date, payload_json,
               source_name, source_url, quality, notes
        FROM bemobi_investor_facts
        WHERE fact_type = ?
        ORDER BY COALESCE(as_of_date, published_date, '') ASC, id ASC
        """,
        (fact_type,),
    )
    return [_decode(row) for row in rows]


async def latest_bemobi_fact(repository, fact_type: str) -> dict[str, Any] | None:
    row = await repository.first(
        """
        SELECT fact_type, fact_key, as_of_date, published_date, payload_json,
               source_name, source_url, quality, notes
        FROM bemobi_investor_facts
        WHERE fact_type = ?
        ORDER BY COALESCE(as_of_date, published_date, '') DESC, id DESC
        LIMIT 1
        """,
        (fact_type,),
    )
    return None if row is None else _decode(row)


def public_fact(fact: dict[str, Any] | None) -> dict[str, Any] | None:
    if fact is None:
        return None
    return {key: value for key, value in fact.items() if not key.startswith("_")}

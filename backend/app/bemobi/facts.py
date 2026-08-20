from __future__ import annotations

import json
from typing import Any


def _decode(row: Any) -> dict[str, Any]:
    payload = json.loads(str(row["payload_json"] or "{}"))
    if not isinstance(payload, dict):
        raise ValueError(f"Ugyldig Bemobi payload for {row['fact_type']}/{row['fact_key']}")
    return {
        **payload,
        "_fact_type": row["fact_type"],
        "_fact_key": row["fact_key"],
        "_as_of_date": row["as_of_date"],
        "_published_date": row["published_date"],
        "_source_name": row["source_name"],
        "_source_url": row["source_url"],
        "_quality": row["quality"],
        "_notes": row["notes"],
    }


def load_bemobi_facts(connection, fact_type: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT fact_type, fact_key, as_of_date, published_date, payload_json,
               source_name, source_url, quality, notes
        FROM bemobi_investor_facts
        WHERE fact_type = ?
        ORDER BY COALESCE(as_of_date, published_date, '') ASC, id ASC
        """,
        (fact_type,),
    ).fetchall()
    return [_decode(row) for row in rows]


def latest_bemobi_fact(connection, fact_type: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT fact_type, fact_key, as_of_date, published_date, payload_json,
               source_name, source_url, quality, notes
        FROM bemobi_investor_facts
        WHERE fact_type = ?
        ORDER BY COALESCE(as_of_date, published_date, '') DESC, id DESC
        LIMIT 1
        """,
        (fact_type,),
    ).fetchone()
    return None if row is None else _decode(row)


def public_fact(fact: dict[str, Any] | None) -> dict[str, Any] | None:
    if fact is None:
        return None
    return {key: value for key, value in fact.items() if not key.startswith("_")}

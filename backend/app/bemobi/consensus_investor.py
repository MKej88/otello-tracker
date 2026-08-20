from __future__ import annotations

from typing import Any

from app.bemobi.consensus import bemobi_consensus as base_bemobi_consensus
from app.bemobi.consensus_history import build_consensus_history


def bemobi_consensus(database_path: str | None = None) -> dict[str, Any]:
    payload = base_bemobi_consensus(database_path)
    if not payload.get("ready"):
        return payload

    beat_miss = payload.get("beat_miss") or []
    forward = (payload.get("forward_consensus") or {}).get("years") or []
    payload["history_link"] = build_consensus_history(
        beat_miss,
        database_path,
        current_forward=forward,
    )
    return payload

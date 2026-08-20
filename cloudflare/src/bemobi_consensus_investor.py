from __future__ import annotations

from typing import Any

from bemobi_consensus import bemobi_consensus as base_bemobi_consensus
from bemobi_consensus_history import build_consensus_history


async def bemobi_consensus(repository) -> dict[str, Any]:
    payload = await base_bemobi_consensus(repository)
    if not payload.get("ready"):
        return payload

    beat_miss = payload.get("beat_miss") or []
    forward = (payload.get("forward_consensus") or {}).get("years") or []
    payload["history_link"] = await build_consensus_history(
        beat_miss,
        repository,
        current_forward=forward,
    )
    return payload

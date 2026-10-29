from __future__ import annotations

from typing import Any

from bemobi_consensus import bemobi_consensus as base_bemobi_consensus


async def bemobi_consensus(
    repository, *, bemobi_payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Kompatibilitetsalias; støtter gjenbruk av ferdig Bemobi-dashboard."""
    return await base_bemobi_consensus(repository, bemobi_payload=bemobi_payload)

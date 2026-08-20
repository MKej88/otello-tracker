from __future__ import annotations

from typing import Any

from bemobi_consensus import bemobi_consensus as base_bemobi_consensus


async def bemobi_consensus(repository) -> dict[str, Any]:
    """Kompatibilitetsalias; base-konsensus inneholder investorhistorikken direkte."""
    return await base_bemobi_consensus(repository)

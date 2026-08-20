from __future__ import annotations

from typing import Any

from app.bemobi.consensus import bemobi_consensus as base_bemobi_consensus


def bemobi_consensus(database_path: str | None = None) -> dict[str, Any]:
    """Kompatibilitetsalias; base-konsensus inneholder investorhistorikken direkte."""
    return base_bemobi_consensus(database_path)

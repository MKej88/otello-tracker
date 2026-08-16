from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.history.curated import _seed_documents, _seed_share_counts

DATA_PATH = Path(__file__).with_name("data") / "otello_2025_share_capital_corrections.json"


def load_2025_share_capital_corrections() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def seed_2025_share_capital_anchors(database_path: str | None = None) -> dict[str, Any]:
    """Seed effective registered share counts around the two 2025 cancellations.

    Report-date anchors alone are insufficient for daily NAV: buybacks after a registered
    capital reduction must use the reduced total share count immediately. These anchors
    therefore use the actual registration dates (5 Mar and 20 Sep 2025), not the later
    report dates or board-resolution dates.
    """
    manifest = load_2025_share_capital_corrections()
    with get_connection(database_path) as connection:
        documents = _seed_documents(connection, manifest)
        written = _seed_share_counts(connection, manifest, documents)
        connection.commit()
        return {
            "manifest_version": manifest["version"],
            "documents": len(documents),
            "share_counts_written": written,
        }

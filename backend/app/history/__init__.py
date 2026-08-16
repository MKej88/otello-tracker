from __future__ import annotations

from app.history.curated import history_status as _history_status
from app.history.curated import seed_curated_history as _seed_curated_history
from app.history.share_capital_2025 import (
    load_2025_share_capital_corrections,
    seed_2025_share_capital_anchors,
)


def seed_curated_history(database_path: str | None = None) -> dict:
    result = _seed_curated_history(database_path)
    capital = seed_2025_share_capital_anchors(database_path)
    result["manifest_version"] = capital["manifest_version"]
    result["share_capital_corrections"] = capital
    return result


def history_status(database_path: str | None = None) -> dict:
    result = _history_status(database_path)
    corrections = load_2025_share_capital_corrections()
    result["manifest_version"] = corrections["version"]
    result["effective_share_capital_corrections"] = {
        "count": len(corrections["share_counts"]),
        "from": min(row["as_of_date"] for row in corrections["share_counts"]),
        "to": max(row["as_of_date"] for row in corrections["share_counts"]),
    }
    return result


__all__ = ["seed_curated_history", "history_status"]

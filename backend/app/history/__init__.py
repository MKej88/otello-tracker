from __future__ import annotations

from app.history.curated import history_status as _history_status
from app.history.curated import seed_curated_history as _seed_curated_history
from app.history.share_capital_2022 import (
    load_2022_share_capital_corrections,
    seed_2022_share_capital_anchors,
)
from app.history.share_capital_2025 import (
    load_2025_share_capital_corrections,
    seed_2025_share_capital_anchors,
)


def seed_curated_history(database_path: str | None = None) -> dict:
    result = _seed_curated_history(database_path)
    capital_2022 = seed_2022_share_capital_anchors(database_path)
    capital_2025 = seed_2025_share_capital_anchors(database_path)
    result["manifest_version"] = capital_2022["manifest_version"]
    result["share_capital_corrections"] = {
        "2022": capital_2022,
        "2025": capital_2025,
    }
    return result


def history_status(database_path: str | None = None) -> dict:
    result = _history_status(database_path)
    corrections_2022 = load_2022_share_capital_corrections()
    corrections_2025 = load_2025_share_capital_corrections()
    rows = [*corrections_2022["share_counts"], *corrections_2025["share_counts"]]
    result["manifest_version"] = corrections_2022["version"]
    result["effective_share_capital_corrections"] = {
        "count": len(rows),
        "from": min(row["as_of_date"] for row in rows),
        "to": max(row["as_of_date"] for row in rows),
    }
    return result


__all__ = ["seed_curated_history", "history_status"]

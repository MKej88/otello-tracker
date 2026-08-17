from __future__ import annotations

from datetime import date
from typing import Any

from app.bemobi.cvm_ipe import collect_bemobi_cvm_news, years_for_refresh
from app.db.runtime_state import get_runtime_state, set_runtime_state

_STATE_PREFIX = "cvm_ipe_historical_complete:"


def collect_bemobi_cvm_news_incremental(
    database_path: str | None = None,
    *,
    target_year: int | None = None,
    timeout: int = 45,
) -> dict[str, Any]:
    """Refresh the current CVM archive daily, but historical archives only until complete.

    CVM's IPE source is organized as annual ZIP files. Re-downloading the previous year
    every day is wasteful on a Raspberry Pi. The current year remains rolling; older
    years are marked complete only after a successful parse/upsert cycle and can be
    retried automatically if an earlier attempt failed.
    """
    current = target_year or date.today().year
    candidates = years_for_refresh(database_path, target_year=current)
    selected = [
        year
        for year in candidates
        if year == current
        or get_runtime_state(f"{_STATE_PREFIX}{year}", database_path) is None
    ]

    if not selected:
        return {
            "years": [],
            "skipped": True,
            "reason": "historical_cvm_archives_already_complete",
            "errors": [],
        }

    result = collect_bemobi_cvm_news(
        database_path,
        years=selected,
        target_year=current,
        timeout=timeout,
    )
    failed_years = {
        int(item["year"])
        for item in result.get("errors", [])
        if item.get("year") is not None
    }
    for year in selected:
        if year != current and year not in failed_years:
            set_runtime_state(f"{_STATE_PREFIX}{year}", "complete", database_path)

    result["historical_years_marked_complete"] = [
        year for year in selected if year != current and year not in failed_years
    ]
    return result

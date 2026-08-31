from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.bemobi.cvm_ipe import collect_bemobi_cvm_news, years_for_refresh
from app.db.runtime_state import get_runtime_state, set_runtime_state

_LAST_SUCCESS_PREFIX = "cvm_ipe_last_success:"
PREVIOUS_YEAR_REFRESH_DAYS = 30


def _refresh_due(year: int, current_year: int, today: date, database_path: str | None) -> bool:
    if year == current_year:
        return True
    last_success = get_runtime_state(f"{_LAST_SUCCESS_PREFIX}{year}", database_path)
    if not last_success:
        return True
    try:
        last_day = date.fromisoformat(last_success[:10])
    except ValueError:
        return True
    if year == current_year - 1:
        # Keep a low-frequency correction check for the previous archive rather than
        # assuming it can never receive a late/restated filing after year-end.
        return today - last_day >= timedelta(days=PREVIOUS_YEAR_REFRESH_DAYS)
    # Older archives are fetched only when years_for_refresh says their local coverage is
    # missing. Once a successful archive has been stored, that function drops them from
    # the candidate set; this branch is therefore only a defensive no-op guard.
    return False


def collect_bemobi_cvm_news_incremental(
    database_path: str | None = None,
    *,
    target_year: int | None = None,
    timeout: int = 45,
    today: date | None = None,
) -> dict[str, Any]:
    """Refresh CVM cheaply without giving up correction coverage.

    The current IPE year remains rolling. The previous year is checked at most every
    30 days to catch late/restated metadata without downloading a second annual ZIP every
    day. Older missing archives are fetched until a successful local copy exists.
    """
    current_day = today or date.today()
    current = target_year or current_day.year
    candidates = years_for_refresh(database_path, target_year=current)
    selected = [
        year
        for year in candidates
        if _refresh_due(year, current, current_day, database_path)
    ]

    if not selected:
        return {
            "years": [],
            "skipped": True,
            "reason": "cvm_archives_not_due",
            "errors": [],
        }

    result = collect_bemobi_cvm_news(
        database_path,
        years=selected,
        target_year=current,
        timeout=timeout,
    )
    raw_successful = result.get("successful_years")
    if not isinstance(raw_successful, list):
        raise ValueError(
            "CVM-innsamlingen mangler eksplisitt bekreftelse på vellykkede år"
        )
    successful = [year for year in selected if year in raw_successful]
    for year in successful:
        set_runtime_state(
            f"{_LAST_SUCCESS_PREFIX}{year}",
            current_day.isoformat(),
            database_path,
        )

    result["successful_years"] = successful
    result["previous_year_refresh_days"] = PREVIOUS_YEAR_REFRESH_DAYS
    return result

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from app.marketdata.oslo_calendar import is_oslo_bors_trading_day


def safe_step(
    name: str,
    function: Callable[[], Any],
    errors: list[dict[str, str]],
) -> Any:
    """Run one refresh step without preventing later steps from running."""
    try:
        return function()
    except Exception as exc:
        errors.append({"step": name, "error": str(exc)})
        return None


def previous_oslo_trading_day(day: date) -> date:
    """Return the latest Oslo Bors trading day before ``day``."""
    candidate = day - timedelta(days=1)
    while not is_oslo_bors_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def eod_is_authoritative(result: Any) -> bool:
    """Return whether an end-of-day result should suppress an intraday fetch."""
    if not isinstance(result, dict):
        return False
    if result.get("status") in {"ok", "no_trade"}:
        return True
    return (
        result.get("status") == "skipped"
        and result.get("reason") == "eod_already_finalized"
    )

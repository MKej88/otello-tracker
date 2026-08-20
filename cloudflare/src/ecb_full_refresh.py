"""Bakoverkompatibel importsti for tidligere Workflow-navn.

Produksjonsvaluta hentes nå direkte fra Norges Bank. Modulen beholdes midlertidig slik at
eldre Workflow-importer ikke brytes under en bakoverkompatibel Worker-deploy.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

try:
    from .norges_bank_full_refresh import (
        ensure_fx_backtest_history,
        refresh_norges_bank_fx,
    )
except ImportError:
    from norges_bank_full_refresh import (
        ensure_fx_backtest_history,
        refresh_norges_bank_fx,
    )


async def refresh_ecb_fx(
    repository,
    *,
    target_date: str,
    lookback_days: int = 21,
    archive_bucket: Any | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Kompatibilitetsalias: henter BRL/NOK og USD/NOK fra Norges Bank."""
    return await refresh_norges_bank_fx(
        repository,
        target_date=target_date,
        lookback_days=lookback_days,
        archive_bucket=archive_bucket,
        fetcher=fetcher,
    )

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

try:
    from .norges_bank_full_refresh import refresh_norges_bank_fx
    from .oslo_calendar import is_oslo_bors_trading_day
except ImportError:
    from norges_bank_full_refresh import refresh_norges_bank_fx
    from oslo_calendar import is_oslo_bors_trading_day

OSLO_TZ = ZoneInfo("Europe/Oslo")
FX_BASE_CURRENCIES = ("BRL", "USD")


def expected_norges_bank_date(now: datetime | None = None) -> str:
    """Latest daily Norges Bank rate expected before the current Oslo day.

    The fast path deliberately targets the previous Norwegian trading day. This avoids
    polling Norges Bank for the current day's fixing before it is published in the
    afternoon, while still repairing a failed overnight refresh quickly.
    """
    current = (now or datetime.now(UTC)).astimezone(OSLO_TZ).date()
    candidate = current - timedelta(days=1)
    while not is_oslo_bors_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate.isoformat()


async def norges_bank_fx_coverage(repository) -> dict[str, Any]:
    rows = await repository.all(
        """
        SELECT fr.base_currency,
               MAX(substr(fr.observed_at,1,10)) AS latest_date,
               MAX(fr.fetched_at) AS latest_fetch
        FROM fx_rates fr
        JOIN sources s ON s.id=fr.source_id
        WHERE fr.quote_currency='NOK'
          AND fr.base_currency IN ('BRL','USD')
          AND s.code='NORGES_BANK'
        GROUP BY fr.base_currency
        ORDER BY fr.base_currency
        """
    )
    pairs = {
        f"{str(row['base_currency'])}/NOK": {
            "latest_date": row.get("latest_date"),
            "latest_fetch": row.get("latest_fetch"),
        }
        for row in rows
        if row.get("base_currency") in FX_BASE_CURRENCIES
    }
    dates = [
        str(pairs[f"{currency}/NOK"].get("latest_date") or "")
        for currency in FX_BASE_CURRENCIES
        if f"{currency}/NOK" in pairs
    ]
    latest_common_date = min(dates) if len(dates) == len(FX_BASE_CURRENCIES) and all(dates) else None
    return {
        "pairs": pairs,
        "latest_common_date": latest_common_date,
        "currency_count": len(pairs),
    }


async def repair_norges_bank_fx_if_stale(
    repository,
    *,
    now: datetime | None = None,
    archive_bucket: Any | None = None,
) -> dict[str, Any]:
    expected_date = expected_norges_bank_date(now)
    before = await norges_bank_fx_coverage(repository)
    latest_before = before.get("latest_common_date")
    if latest_before is not None and str(latest_before) >= expected_date:
        return {
            "status": "skipped",
            "reason": "fx_current",
            "expected_date": expected_date,
            "latest_common_date": latest_before,
            "network_fetches_avoided": True,
            "repaired": False,
        }

    refresh = await refresh_norges_bank_fx(
        repository,
        target_date=expected_date,
        lookback_days=7,
        archive_bucket=archive_bucket,
    )
    after = await norges_bank_fx_coverage(repository)
    latest_after = after.get("latest_common_date")
    if latest_after is None or str(latest_after) < expected_date:
        return {
            **refresh,
            "status": "partial",
            "reason": "expected_fx_date_still_missing",
            "expected_date": expected_date,
            "latest_common_date": latest_after,
            "repaired": False,
        }

    return {
        **refresh,
        "status": "ok",
        "expected_date": expected_date,
        "latest_common_date": latest_after,
        "repaired": True,
    }

from __future__ import annotations

from decimal import Decimal
from typing import Any

try:
    from .nav_refresh import (
        CORE_CALCULATION_VERSION,
        FULL_CALCULATION_VERSION,
        refresh_core_nav_if_dirty,
        refresh_daily_cash_if_dirty,
        refresh_full_nav_if_dirty,
        refresh_other_net_assets_if_dirty,
    )
except ImportError:
    from nav_refresh import (
        CORE_CALCULATION_VERSION,
        FULL_CALCULATION_VERSION,
        refresh_core_nav_if_dirty,
        refresh_daily_cash_if_dirty,
        refresh_full_nav_if_dirty,
        refresh_other_net_assets_if_dirty,
    )

MAX_FX_LOOKBACK_DAYS = 7


async def _norges_bank_rate(repository, base: str, day: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT fr.id, substr(fr.observed_at,1,10) AS rate_date, fr.rate
        FROM fx_rates fr
        JOIN sources s ON s.id=fr.source_id
        WHERE fr.base_currency=? AND fr.quote_currency='NOK'
          AND s.code='NORGES_BANK'
          AND substr(fr.observed_at,1,10) <= ?
          AND substr(fr.observed_at,1,10) >= date(?, '-' || ? || ' days')
        ORDER BY fr.observed_at DESC, fr.id DESC
        LIMIT 1
        """,
        (base, day, day, MAX_FX_LOOKBACK_DAYS),
    )


async def _normalize_fx_derived_cash(repository, *, start_date: str, end_date: str) -> dict[str, int]:
    """Revalue stored original-currency cash facts with direct Norges Bank NOK rates.

    The original currency amount remains the economic fact. Only the derived NOK amount
    and its recorded FX rate are refreshed. NOK movements are intentionally untouched.
    """
    anchors = await repository.all(
        """
        SELECT id, as_of_date, reported_amount, reported_currency
        FROM cash_anchors
        WHERE anchor_type='REPORTED'
          AND reported_amount IS NOT NULL
          AND reported_currency IN ('USD','BRL')
          AND as_of_date >= ? AND as_of_date <= ?
        ORDER BY as_of_date, id
        """,
        (start_date, end_date),
    )
    anchor_updates = 0
    for anchor in anchors:
        fx = await _norges_bank_rate(repository, str(anchor["reported_currency"]), str(anchor["as_of_date"]))
        if fx is None:
            continue
        amount_nok = Decimal(str(anchor["reported_amount"])) * Decimal(str(fx["rate"]))
        await repository.run(
            """
            UPDATE cash_anchors
            SET amount_nok=?, fx_rate_to_nok=?
            WHERE id=?
            """,
            (format(amount_nok, "f"), str(fx["rate"]), int(anchor["id"])),
        )
        anchor_updates += 1

    movements = await repository.all(
        """
        SELECT id, movement_date, amount_original, currency
        FROM cash_movements
        WHERE amount_original IS NOT NULL
          AND currency IN ('USD','BRL')
          AND movement_date >= ? AND movement_date <= ?
        ORDER BY movement_date, id
        """,
        (start_date, end_date),
    )
    movement_updates = 0
    for movement in movements:
        fx = await _norges_bank_rate(repository, str(movement["currency"]), str(movement["movement_date"]))
        if fx is None:
            continue
        amount_nok = Decimal(str(movement["amount_original"])) * Decimal(str(fx["rate"]))
        await repository.run(
            """
            UPDATE cash_movements
            SET amount_nok=?, fx_rate_to_nok=?
            WHERE id=?
            """,
            (format(amount_nok, "f"), str(fx["rate"]), int(movement["id"])),
        )
        movement_updates += 1

    return {
        "cash_anchors_updated": anchor_updates,
        "cash_movements_updated": movement_updates,
    }


async def _existing_core_dates(repository, *, start_date: str, end_date: str) -> list[dict[str, Any]]:
    return await repository.all(
        """
        SELECT substr(as_of_at,1,10) AS nav_date, nav_per_share_nok
        FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope='CORE'
          AND substr(as_of_at,1,10) >= ? AND substr(as_of_at,1,10) <= ?
        ORDER BY as_of_at
        """,
        (CORE_CALCULATION_VERSION, start_date, end_date),
    )


async def rebuild_existing_nav_with_norges_bank(
    repository,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Rebuild existing derived NAV history after the direct Norges Bank backfill.

    This does not manufacture older NAV dates. It only revisits dates that already have
    a CORE snapshot, so the historical coverage stays identical while FX provenance and
    NOK-valued derived amounts are refreshed deterministically.
    """
    normalized = await _normalize_fx_derived_cash(
        repository,
        start_date=start_date,
        end_date=end_date,
    )
    dates = await _existing_core_dates(repository, start_date=start_date, end_date=end_date)
    failures: list[dict[str, Any]] = []
    changed = 0
    unchanged = 0
    largest_changes: list[dict[str, Any]] = []

    for row in dates:
        nav_date = str(row["nav_date"])
        before = Decimal(str(row["nav_per_share_nok"]))
        steps = {
            "daily_cash": await refresh_daily_cash_if_dirty(repository, nav_date),
            "daily_other_net_assets": await refresh_other_net_assets_if_dirty(repository, nav_date),
            "daily_core_nav": await refresh_core_nav_if_dirty(repository, nav_date),
            "daily_full_nav": await refresh_full_nav_if_dirty(repository, nav_date),
        }
        not_ready = [name for name, result in steps.items() if result.get("status") != "ok"]
        if not_ready:
            failures.append({"date": nav_date, "not_ready_layers": not_ready})
            continue

        after_row = await repository.first(
            """
            SELECT nav_per_share_nok
            FROM nav_snapshots
            WHERE as_of_at=? AND calculation_version=? AND nav_scope='CORE'
            LIMIT 1
            """,
            (f"{nav_date}T23:59:59Z", CORE_CALCULATION_VERSION),
        )
        if after_row is None:
            failures.append({"date": nav_date, "not_ready_layers": ["daily_core_nav_readback"]})
            continue
        after = Decimal(str(after_row["nav_per_share_nok"]))
        delta = after - before
        if delta == 0:
            unchanged += 1
        else:
            changed += 1
            largest_changes.append(
                {
                    "date": nav_date,
                    "before_nav_per_share_nok": float(before),
                    "after_nav_per_share_nok": float(after),
                    "change_nok": float(delta),
                    "absolute_change_nok": float(abs(delta)),
                }
            )

    largest_changes.sort(key=lambda item: item["absolute_change_nok"], reverse=True)
    return {
        "status": "partial" if failures else "ok",
        "from": start_date,
        "to": end_date,
        "dates_seen": len(dates),
        "dates_changed": changed,
        "dates_unchanged": unchanged,
        "dates_not_ready": len(failures),
        "largest_changes": largest_changes[:10],
        "failures": failures[:25],
        "cash_normalization": normalized,
        "core_calculation_version": CORE_CALCULATION_VERSION,
        "full_calculation_version": FULL_CALCULATION_VERSION,
        "fx_policy": "NORGES_BANK_DIRECT_NOK_PREFERRED_ECB_FALLBACK",
    }

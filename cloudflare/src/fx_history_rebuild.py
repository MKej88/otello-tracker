from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

try:
    from .history_rebuild_state import (
        HISTORY_REBUILD_CHUNK_DAYS,
        history_window_complete,
        mark_history_window_complete,
        next_history_rebuild_chunk,
    )
    from .nav_refresh import (
        CORE_CALCULATION_VERSION,
        FULL_CALCULATION_VERSION,
        refresh_core_nav_if_dirty,
        refresh_daily_cash_if_dirty,
        refresh_full_nav_if_dirty,
        refresh_other_net_assets_if_dirty,
    )
except ImportError:
    from history_rebuild_state import (
        HISTORY_REBUILD_CHUNK_DAYS,
        history_window_complete,
        mark_history_window_complete,
        next_history_rebuild_chunk,
    )
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
    floor_date = (date.fromisoformat(day) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT fr.id, substr(fr.observed_at,1,10) AS rate_date, fr.rate
        FROM fx_rates fr
        JOIN sources s ON s.id=fr.source_id
        WHERE fr.base_currency=? AND fr.quote_currency='NOK'
          AND s.code='NORGES_BANK'
          AND substr(fr.observed_at,1,10) <= ?
          AND substr(fr.observed_at,1,10) >= ?
        ORDER BY fr.observed_at DESC, fr.id DESC
        LIMIT 1
        """,
        (base, day, floor_date),
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
        fx = await _norges_bank_rate(
            repository,
            str(anchor["reported_currency"]),
            str(anchor["as_of_date"]),
        )
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
        fx = await _norges_bank_rate(
            repository,
            str(movement["currency"]),
            str(movement["movement_date"]),
        )
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
        SELECT substr(c.as_of_at,1,10) AS nav_date,
               c.nav_per_share_nok,
               EXISTS(
                 SELECT 1 FROM nav_snapshots f
                 WHERE f.as_of_at=c.as_of_at
                   AND f.calculation_version=?
                   AND f.nav_scope='FULL'
               ) AS had_full
        FROM nav_snapshots c
        WHERE c.calculation_version=? AND c.nav_scope='CORE'
          AND substr(c.as_of_at,1,10) >= ? AND substr(c.as_of_at,1,10) <= ?
        ORDER BY c.as_of_at
        """,
        (FULL_CALCULATION_VERSION, CORE_CALCULATION_VERSION, start_date, end_date),
    )


async def rebuild_existing_nav_with_norges_bank(
    repository,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Rebuild existing derived NAV history after the direct Norges Bank backfill.

    Existing CORE dates are rebuilt. ONA/FULL are rebuilt only where a FULL snapshot
    already existed, so the job never manufactures additional historical model coverage.
    A single Workflow invocation only processes a small contiguous checkpointed chunk.
    That bounds CPU/subrequests and lets a killed historical bootstrap resume instead of
    repeating an entire calendar year.
    """
    if await history_window_complete(repository, start_date=start_date, end_date=end_date):
        return {
            "status": "ok",
            "skipped": True,
            "reason": "history_window_already_complete",
            "from": start_date,
            "to": end_date,
            "requested_from": start_date,
            "requested_to": end_date,
            "continuation_required": False,
            "dates_seen": 0,
            "full_dates_seen": 0,
            "dates_changed": 0,
            "dates_unchanged": 0,
            "dates_not_ready": 0,
            "largest_changes": [],
            "failures": [],
            "cash_normalization": {
                "cash_anchors_updated": 0,
                "cash_movements_updated": 0,
            },
            "core_calculation_version": CORE_CALCULATION_VERSION,
            "full_calculation_version": FULL_CALCULATION_VERSION,
            "fx_policy": "NORGES_BANK_DIRECT_NOK_PREFERRED_ECB_FALLBACK",
        }

    chunk = await next_history_rebuild_chunk(
        repository,
        start_date=start_date,
        end_date=end_date,
        max_days=HISTORY_REBUILD_CHUNK_DAYS,
    )
    if chunk is None:
        return {
            "status": "ok",
            "skipped": True,
            "reason": "history_window_checkpoint_exhausted",
            "from": start_date,
            "to": end_date,
            "requested_from": start_date,
            "requested_to": end_date,
            "continuation_required": False,
            "dates_seen": 0,
            "full_dates_seen": 0,
            "dates_changed": 0,
            "dates_unchanged": 0,
            "dates_not_ready": 0,
            "largest_changes": [],
            "failures": [],
            "cash_normalization": {
                "cash_anchors_updated": 0,
                "cash_movements_updated": 0,
            },
            "core_calculation_version": CORE_CALCULATION_VERSION,
            "full_calculation_version": FULL_CALCULATION_VERSION,
            "fx_policy": "NORGES_BANK_DIRECT_NOK_PREFERRED_ECB_FALLBACK",
        }

    chunk_start, chunk_end = chunk
    normalized = await _normalize_fx_derived_cash(
        repository,
        start_date=chunk_start,
        end_date=chunk_end,
    )
    dates = await _existing_core_dates(repository, start_date=chunk_start, end_date=chunk_end)
    failures: list[dict[str, Any]] = []
    changed = 0
    unchanged = 0
    full_dates_seen = 0
    largest_changes: list[dict[str, Any]] = []

    for row in dates:
        nav_date = str(row["nav_date"])
        before = Decimal(str(row["nav_per_share_nok"]))
        had_full = bool(row.get("had_full"))

        steps: dict[str, dict[str, Any]] = {
            "daily_cash": await refresh_daily_cash_if_dirty(repository, nav_date),
        }
        if had_full:
            full_dates_seen += 1
            steps["daily_other_net_assets"] = await refresh_other_net_assets_if_dirty(
                repository, nav_date
            )
        steps["daily_core_nav"] = await refresh_core_nav_if_dirty(repository, nav_date)
        if had_full:
            steps["daily_full_nav"] = await refresh_full_nav_if_dirty(repository, nav_date)

        not_ready = [name for name, result in steps.items() if result.get("status") != "ok"]
        if not_ready:
            failures.append({"date": nav_date, "not_ready_layers": not_ready, "had_full": had_full})
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
            failures.append(
                {"date": nav_date, "not_ready_layers": ["daily_core_nav_readback"], "had_full": had_full}
            )
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
    chunk_ok = not failures
    if chunk_ok:
        await mark_history_window_complete(
            repository,
            start_date=chunk_start,
            end_date=chunk_end,
        )
    continuation_required = chunk_ok and chunk_end < end_date
    status = "partial" if failures or continuation_required else "ok"
    next_from = None
    if continuation_required:
        next_from = (date.fromisoformat(chunk_end) + timedelta(days=1)).isoformat()
    return {
        "status": status,
        "from": chunk_start,
        "to": chunk_end,
        "requested_from": start_date,
        "requested_to": end_date,
        "chunk_days": HISTORY_REBUILD_CHUNK_DAYS,
        "continuation_required": continuation_required,
        "next_from": next_from,
        "dates_seen": len(dates),
        "full_dates_seen": full_dates_seen,
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

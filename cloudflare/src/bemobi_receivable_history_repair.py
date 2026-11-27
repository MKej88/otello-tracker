"""Bounded replay of historical BMOB3 receivables after late official distributions.

A newly ingested JCP entitlement or documented net estimate updates current NAV,
but a previous ex-date may have a materialized zero or gross-only ONA/FULL snapshot.
Recompute only those *existing* date layers, with the same production NAV model,
under the Cloudflare full-refresh writer lease. Never insert arbitrary NAV facts.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from estimated_nav_history import _estimated_point
from estimated_nav_history_materialization import _write_point_and_remove_retry
from nav_refresh import (
    FULL_CALCULATION_VERSION,
    _receivable_actions,
    _receivable_for_day,
    refresh_full_nav_if_dirty,
    refresh_other_net_assets_if_dirty,
)

MAX_REPLAY_DAYS = 10
LOOKBACK_DAYS = 21


async def repair_late_bemobi_receivable_history(
    repository, *, target_date: str,
) -> dict:
    """Replay bounded missing receivables; preserve all issuer/FX provenance."""
    end = date.fromisoformat(target_date)
    start = (end - timedelta(days=LOOKBACK_DAYS)).isoformat()
    existing = await repository.all(
        """
        SELECT DISTINCT o.estimate_date, o.associated_receivable_nok, o.receivable_quality
        FROM other_net_assets_daily_estimates o
        JOIN nav_snapshots n
          ON substr(n.as_of_at,1,10)=o.estimate_date
         AND n.nav_scope='FULL' AND n.calculation_version=?
        WHERE o.estimate_date BETWEEN ? AND ?
          AND (CAST(o.associated_receivable_nok AS REAL)=0
               OR o.receivable_quality='ESTIMATED_GROSS')
        ORDER BY o.estimate_date
        """,
        (FULL_CALCULATION_VERSION, start, target_date),
    )
    if not existing:
        return {"status": "ok", "repaired": [], "attempted": 0, "skipped": 0}

    # Uses only source-documented corporate actions with holdings at ex-date.
    actions = await _receivable_actions(repository)
    eligible = [a for a in actions if
                a.get("ex_date") and a.get("payment_date")
                and str(a["ex_date"]) <= target_date
                and str(a["payment_date"]) > start
                and a.get("source_document_id") is not None]
    if not eligible:
        return {"status": "ok", "repaired": [], "attempted": 0,
                "skipped": len(existing)}
    candidates = []
    by_day = {str(row['estimate_date']): row for row in existing}
    for row in existing:
        day = str(row["estimate_date"])
        if any(str(a["ex_date"]) <= day < str(a["payment_date"]) for a in eligible):
            candidates.append(day)
    zero_candidates = [day for day in candidates if Decimal(str(by_day[day]['associated_receivable_nok'])) == 0]
    if len(zero_candidates) > MAX_REPLAY_DAYS:
        return {"status": "partial", "reason": "bounded_replay_limit",
                "candidate_count": len(candidates),
                "max_days": MAX_REPLAY_DAYS, "repaired": []}

    repaired = []
    errors = []
    for day in candidates:
        expectation = await _receivable_for_day(repository, day, actions)
        if expectation is None:
            errors.append({"date": day, "reason": "missing_brl_nok"})
            continue
        amount_nok, quality, components = expectation
        if amount_nok <= 0:
            continue
        stored = by_day[day]
        if Decimal(str(stored['associated_receivable_nok'])) != 0 and quality not in {
            'ESTIMATED_NET', 'REPORTED_CALIBRATED'
        }:
            continue
        if len(repaired) + len(errors) >= MAX_REPLAY_DAYS:
            errors.append({'date': day, 'reason': 'bounded_replay_limit'})
            break
        if not any(int(c.get("corporate_action_id") or 0) == int(a["id"])
                   for c in components for a in eligible):
            errors.append({"date": day, "reason": "missing_action_provenance"})
            continue
        ona = await refresh_other_net_assets_if_dirty(repository, day)
        if ona.get("status") != "ok":
            errors.append({"date": day, "reason": "ona_not_ready",
                           "detail": str(ona.get("reason") or "")[:120]})
            continue
        verified = await repository.first(
            "SELECT associated_receivable_nok, receivable_quality FROM other_net_assets_daily_estimates "
            "WHERE estimate_date=? LIMIT 1", (day,),
        )
        actual = Decimal(str((verified or {}).get("associated_receivable_nok") or "0"))
        if (abs(actual - amount_nok) > Decimal("0.01")
                or (quality == 'ESTIMATED_NET' and (verified or {}).get('receivable_quality') != quality)):
            errors.append({"date": day, "reason": "ona_receivable_mismatch"})
            continue
        full = await refresh_full_nav_if_dirty(repository, day)
        if full.get("status") != "ok":
            errors.append({"date": day, "reason": "full_nav_not_ready",
                           "detail": str(full.get("reason") or "")[:120]})
            continue
        point = await _estimated_point(repository, day)
        if not point.get("ready"):
            errors.append({"date": day, "reason": "estimated_history_not_ready",
                           "detail": str(point.get("reason") or "")[:120]})
            continue
        # Atomic materialized-point/cache invalidation in the existing model.
        await _write_point_and_remove_retry(repository, day, point)
        repaired.append({
            "date": day,
            "receivable_nok": format(actual, "f"),
            "quality": quality,
            "action_ids": sorted(set(int(x["corporate_action_id"]) for x in components)),
            "full_nav_status": full["status"],
            "materialized_history": True,
        })
    return {
        "status": "partial" if errors else "ok",
        "lookback_start": start,
        "target_date": target_date,
        "attempted": len(candidates),
        "repaired": repaired,
        "errors": errors,
    }

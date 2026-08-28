from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.dashboard import dashboard_history
from app.db.connection import get_connection
from app.economic_nav_investor import economic_nav_summary
from app.estimated_nav_history_display import _report_split_state, estimated_nav_history


def _float(value: Decimal | str | int | float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


def _percentile(sorted_values: list[Decimal], quantile: Decimal) -> Decimal | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = Decimal(len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - Decimal(lower)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def _discount_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid: list[tuple[str, Decimal]] = []
    for row in rows:
        raw = row.get("discount_pct")
        if raw is not None:
            valid.append((str(row.get("date") or ""), Decimal(str(raw))))
    if not valid:
        return {
            "count": 0, "current_discount_pct": None, "average_discount_pct": None,
            "median_discount_pct": None, "p10_discount_pct": None, "p25_discount_pct": None,
            "p75_discount_pct": None, "p90_discount_pct": None, "minimum_discount_pct": None,
            "minimum_discount_date": None, "maximum_discount_pct": None, "maximum_discount_date": None,
            "current_percentile": None, "premium_observation_count": 0,
        }
    values = sorted(value for _, value in valid)
    current = valid[-1][1]
    below = sum(1 for value in values if value < current)
    equal = sum(1 for value in values if value == current)
    current_percentile = (Decimal(below) + Decimal(equal) / Decimal("2")) / Decimal(len(values)) * Decimal("100")
    minimum_date, minimum = min(valid, key=lambda item: (item[1], item[0]))
    maximum_date, maximum = max(valid, key=lambda item: (item[1], item[0]))
    return {
        "count": len(values),
        "current_discount_pct": _float(current),
        "average_discount_pct": _float(sum(values, Decimal("0")) / Decimal(len(values))),
        "median_discount_pct": _float(_percentile(values, Decimal("0.50"))),
        "p10_discount_pct": _float(_percentile(values, Decimal("0.10"))),
        "p25_discount_pct": _float(_percentile(values, Decimal("0.25"))),
        "p75_discount_pct": _float(_percentile(values, Decimal("0.75"))),
        "p90_discount_pct": _float(_percentile(values, Decimal("0.90"))),
        "minimum_discount_pct": _float(minimum), "minimum_discount_date": minimum_date,
        "maximum_discount_pct": _float(maximum), "maximum_discount_date": maximum_date,
        "current_percentile": _float(current_percentile),
        "premium_observation_count": sum(1 for value in values if value < 0),
    }


def _latest_share_count(share_counts: list[dict[str, Any]], day: str) -> dict[str, Any] | None:
    latest = None
    for row in share_counts:
        if str(row.get("effective_from") or "") > day:
            break
        latest = row
    return latest


def _apply_buyback_share_adjustments(rows: list[dict[str, Any]], periods: list[dict[str, Any]], transactions: list[dict[str, Any]], share_counts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Revalue per-share NAV on exact NewsWeb buyback dates without guessing."""
    tx_by_period: dict[int, list[dict[str, Any]]] = {}
    for raw in transactions:
        tx_by_period.setdefault(int(raw["weekly_buyback_id"]), []).append(dict(raw))
    for items in tx_by_period.values():
        items.sort(key=lambda item: (str(item["trade_date"]), int(item.get("id") or 0)))
    valid_periods: list[dict[str, Any]] = []
    for raw in periods:
        period = dict(raw)
        items = tx_by_period.get(int(period["id"]), [])
        if not items or any(str(item.get("quality")) == "REQUIRES_REVIEW" for item in items):
            continue
        weekly_shares = int(period.get("weekly_shares") or 0)
        if sum(int(item["shares"]) for item in items) != weekly_shares:
            continue
        period_start, period_end = str(period["period_start"]), str(period["period_end"])
        start_count, end_count = _latest_share_count(share_counts, period_start), _latest_share_count(share_counts, period_end)
        if start_count is None or end_count is None or int(start_count["total_shares"]) != int(end_count["total_shares"]):
            continue
        treasury_after = period.get("treasury_shares_after")
        if treasury_after is None or int(start_count["treasury_shares"]) + weekly_shares != int(treasury_after):
            continue
        valid_periods.append({**period, "transactions": items, "total_shares": int(end_count["total_shares"]), "period_end_outstanding": int(end_count["total_shares"]) - int(treasury_after)})
    adjusted_rows: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        day = str(row.get("date") or "")
        row["share_count_quality"] = "STORED_SNAPSHOT"
        row["buyback_adjusted_shares"] = 0
        for period in valid_periods:
            if not (str(period["period_start"]) <= day <= str(period["period_end"])):
                continue
            future_buys = sum(int(item["shares"]) for item in period["transactions"] if day < str(item["trade_date"]) <= str(period["period_end"]))
            adjusted_outstanding = int(period["period_end_outstanding"]) + future_buys
            if adjusted_outstanding <= 0 or adjusted_outstanding > int(period["total_shares"]):
                break
            original_outstanding = int(row.get("shares_outstanding") or adjusted_outstanding)
            nav_total, otec_price = row.get("nav_total_nok"), row.get("otec_price_nok")
            if nav_total is None or otec_price is None:
                break
            nav_per_share = Decimal(str(nav_total)) / Decimal(adjusted_outstanding)
            if nav_per_share == 0:
                break
            row["shares_outstanding"] = adjusted_outstanding
            row["nav_per_share_nok"] = nav_per_share
            row["discount_pct"] = (Decimal("1") - Decimal(str(otec_price)) / nav_per_share) * Decimal("100")
            row["share_count_quality"] = "NEWSWEB_DAILY_RECONCILED"
            row["buyback_adjusted_shares"] = original_outstanding - adjusted_outstanding
            row["buyback_period_end"] = period["period_end"]
            break
        adjusted_rows.append(row)
    return adjusted_rows


def _history_point(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": str(row["date"]), "nav_per_share": _float(row.get("nav_per_share_nok")),
        "otec_price": _float(row.get("otec_price_nok")), "discount_pct": _float(row.get("discount_pct")),
        "cash_mnok": None if row.get("cash_estimate_nok") is None else _float(row["cash_estimate_nok"]) / 1_000_000,
        "other_net_assets_mnok": None if row.get("other_net_assets_nok") is None else _float(row["other_net_assets_nok"]) / 1_000_000,
        "shares_outstanding": int(row["shares_outstanding"]) if row.get("shares_outstanding") is not None else None,
        "share_count_quality": str(row.get("share_count_quality") or "STORED_SNAPSHOT"),
        "buyback_adjusted_shares": int(row.get("buyback_adjusted_shares") or 0),
        "status": str(row.get("status") or "UNKNOWN"),
    }


def _downsample(points: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if len(points) <= max_points:
        return points
    indexes = sorted({round(index * (len(points) - 1) / (max_points - 1)) for index in range(max_points)})
    return [points[index] for index in indexes]


def _economic_reference(database_path: str | None) -> dict[str, Any]:
    economic = economic_nav_summary(database_path)
    if not economic.get("ready"):
        return {"ready": False, "reason": economic.get("reason") or "economic_nav_not_ready", "as_of_date": economic.get("as_of_date")}
    return {"ready": True, "as_of_date": economic.get("as_of_date"), "quality": economic.get("quality"), "nav_per_share": economic.get("nav_per_share"), "discount_pct": economic.get("discount_pct"), "conservative_nav_per_share": economic.get("conservative_nav_per_share"), "conservative_discount_pct": economic.get("conservative_discount_pct")}


def _investment_report_for_nav_date(
    database_path: str | None,
    nav_date: str,
) -> dict[str, Any]:
    if not nav_date:
        return {"ready": False, "reason": "missing_nav_date"}
    with get_connection(database_path) as connection:
        anchor = connection.execute(
            """
            SELECT as_of_date
            FROM cash_anchors
            WHERE anchor_type='REPORTED' AND as_of_date<=?
            ORDER BY as_of_date DESC, id DESC LIMIT 1
            """,
            (nav_date,),
        ).fetchone()
    if anchor is None:
        return {"ready": False, "reason": "missing_reported_cash_anchor"}
    return _report_split_state(database_path, str(anchor["as_of_date"]))


def _apply_other_share_change_split(
    change: dict[str, Any],
    start_report: dict[str, Any],
    current_report: dict[str, Any],
) -> bool:
    drivers = change.get("drivers") or []
    if not isinstance(drivers, list):
        return False
    other_ona = next((item for item in drivers if item.get("key") == "other_ona"), None)
    if other_ona is None or not start_report.get("ready") or not current_report.get("ready"):
        return False

    share_change = change.get("share_count_change") or {}
    start_shares = int(share_change.get("start_shares") or 0)
    current_shares = int(share_change.get("current_shares") or 0)
    if start_shares <= 0 or current_shares <= 0:
        return False

    start_alliance_nok = Decimal(str(start_report.get("alliance_report_nok") or "0"))
    current_alliance_nok = Decimal(str(current_report.get("alliance_report_nok") or "0"))
    alliance_delta_nok = current_alliance_nok - start_alliance_nok
    reciprocal_scale = (
        Decimal("1") / Decimal(start_shares)
        + Decimal("1") / Decimal(current_shares)
    ) / Decimal("2")

    original_other_ona_nok = Decimal(str(other_ona.get("amount_mnok") or "0")) * Decimal("1000000")
    original_other_ona_per_share = Decimal(str(other_ona.get("per_share_nok") or "0"))
    residual_ona_nok = original_other_ona_nok - alliance_delta_nok
    other_ona["label"] = "Andre rapporterte eiendeler og forpliktelser"
    other_ona["amount_mnok"] = float(residual_ona_nok / Decimal("1000000"))
    other_ona["per_share_nok"] = float(
        original_other_ona_per_share - alliance_delta_nok * reciprocal_scale
    )
    other_ona["details"] = {
        **(other_ona.get("details") or {}),
        "start_amount_mnok": None,
        "current_amount_mnok": None,
        "alliance_venture_spring_split": True,
        "alliance_change_mnok": float(alliance_delta_nok / Decimal("1000000")),
    }

    alliance_driver = {
        "key": "alliance_venture_spring",
        "label": "Alliance Venture Spring AS",
        "amount_mnok": float(alliance_delta_nok / Decimal("1000000")),
        "per_share_nok": float(alliance_delta_nok * reciprocal_scale),
        "impact_kind": "TOTAL_AND_PER_SHARE",
        "details": {
            "start_amount_mnok": float(start_alliance_nok / Decimal("1000000")),
            "current_amount_mnok": float(current_alliance_nok / Decimal("1000000")),
            "start_report_date": start_report.get("resolved_report_anchor_date"),
            "current_report_date": current_report.get("resolved_report_anchor_date"),
            "display_policy": "FIXED_AT_LAST_REPORT",
        },
    }
    drivers.insert(drivers.index(other_ona), alliance_driver)
    change["other_share_split_status"] = {
        "ready": True,
        "policy": "LIFE360_AND_ALLIANCE_SEPARATE_FROM_OTHER_ONA",
        "start_report_date": start_report.get("resolved_report_anchor_date"),
        "current_report_date": current_report.get("resolved_report_anchor_date"),
    }
    return True


def _estimated_extension(database_path: str | None, days: int) -> dict[str, Any]:
    result = estimated_nav_history(database_path, days=days)
    change = result.get("change") or {}
    if change.get("ready"):
        start_report = _investment_report_for_nav_date(
            database_path,
            str(change.get("resolved_start") or ""),
        )
        current_report = _investment_report_for_nav_date(
            database_path,
            str(change.get("current_date") or ""),
        )
        if not _apply_other_share_change_split(change, start_report, current_report):
            change["other_share_split_status"] = {
                "ready": False,
                "start_reason": start_report.get("reason"),
                "current_reason": current_report.get("reason"),
            }
    return {**result, "statistics": _discount_statistics(result.get("points") or [])}


def discount_history(database_path: str | None = None, *, days: int = 365, max_points: int = 600) -> dict[str, Any]:
    """Validated legacy history plus the user-facing historical Estimert NAV series."""
    days = max(30, min(int(days), 3650))
    max_points = max(50, min(int(max_points), 1000))
    history = dashboard_history(database_path, days=days, max_points=max_points)
    estimated = _estimated_extension(database_path, days)
    if not history.get("ready"):
        return {**history, "period_days": days, "statistics": _discount_statistics([]), "current_economic": _economic_reference(database_path), "estimated": estimated}
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """WITH ranked AS (
              SELECT substr(as_of_at,1,10) AS date,nav_total_nok,nav_per_share_nok,otec_price_nok,discount_pct,
                     cash_estimate_nok,other_net_assets_nok,shares_outstanding,status,
                     ROW_NUMBER() OVER (PARTITION BY substr(as_of_at,1,10) ORDER BY as_of_at DESC,id DESC) AS rn
              FROM nav_snapshots WHERE calculation_version=? AND nav_scope=? AND substr(as_of_at,1,10)>=? AND substr(as_of_at,1,10)<=?
                AND nav_per_share_nok IS NOT NULL AND otec_price_nok IS NOT NULL AND discount_pct IS NOT NULL)
            SELECT date,nav_total_nok,nav_per_share_nok,otec_price_nok,discount_pct,cash_estimate_nok,other_net_assets_nok,shares_outstanding,status FROM ranked WHERE rn=1 ORDER BY date""",
            (history["calculation_version"], history["model_scope"], history["from"], history["to"]),
        ).fetchall()
        periods = connection.execute("SELECT id,period_start,trade_date AS period_end,shares AS weekly_shares,treasury_shares_after FROM buybacks WHERE period_start IS NOT NULL AND treasury_shares_after IS NOT NULL AND trade_date>=? AND period_start<=? ORDER BY period_start,trade_date,id", (history["from"], history["to"])).fetchall()
        transactions = connection.execute("SELECT d.id,d.weekly_buyback_id,d.trade_date,d.shares,d.quality FROM buyback_daily_transactions d JOIN buybacks b ON b.id=d.weekly_buyback_id WHERE b.period_start IS NOT NULL AND b.trade_date>=? AND b.period_start<=? ORDER BY d.weekly_buyback_id,d.trade_date,d.id", (history["from"], history["to"])).fetchall()
        share_counts = connection.execute("SELECT id,effective_from,total_shares,treasury_shares,outstanding_shares FROM otello_share_counts WHERE effective_from<=? ORDER BY effective_from,id", (history["to"],)).fetchall()
        daily_rows = _apply_buyback_share_adjustments([dict(row) for row in rows], [dict(row) for row in periods], [dict(row) for row in transactions], [dict(row) for row in share_counts])
    statistics = _discount_statistics(daily_rows)
    daily_points = [_history_point(row) for row in daily_rows]
    points = _downsample(daily_points, max_points)
    latest_point = daily_points[-1] if daily_points else None
    adjusted_observations = sum(1 for row in daily_rows if str(row.get("share_count_quality")) == "NEWSWEB_DAILY_RECONCILED")
    return {
        "ready": True, "data_status": history.get("data_status"), "period_days": days,
        "from": daily_points[0]["date"] if daily_points else history.get("from"), "to": daily_points[-1]["date"] if daily_points else history.get("to"),
        "raw_count": len(daily_points), "source_snapshot_count": history.get("raw_count"), "point_count": len(points),
        "basis": {"type": "VALIDATED_NAV_HISTORY", "model_scope": history.get("model_scope"), "calculation_version": history.get("calculation_version"), "observation_policy": "LATEST_COMPLETE_SNAPSHOT_PER_DATE", "share_count_policy": "NEWSWEB_DAILY_RECONCILED_WHEN_EXACT", "buyback_adjusted_observation_count": adjusted_observations, "note": "Historiske persentiler bruker siste komplette validerte FULL/CORE NAV per dato. Når NewsWeb-transaksjoner avstemmer hele ukesmeldingen, justeres utestående aksjer på faktiske handelsdatoer og NAV/aksje samt rabatt beregnes på nytt. Perioder som ikke kan avstemmes eksakt beholdes uendret. Dagens økonomiske investor-NAV vises separat."},
        "statistics": statistics,
        "current_validated": None if latest_point is None else {"date": latest_point.get("date"), "nav_per_share": latest_point.get("nav_per_share"), "otec_price": latest_point.get("otec_price"), "discount_pct": latest_point.get("discount_pct"), "shares_outstanding": latest_point.get("shares_outstanding"), "share_count_quality": latest_point.get("share_count_quality")},
        "current_economic": _economic_reference(database_path), "points": points, "estimated": estimated,
    }
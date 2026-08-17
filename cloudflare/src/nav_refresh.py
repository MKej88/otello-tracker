from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from cash_refresh import decimal_text, nearest_fx, rebuild_daily_cash_if_changed, stable_hash
from ona_refresh import rebuild_other_net_assets_for_date
from option_refresh import preferred_price
from repository import D1WriteRepository

CORE_VERSION = "core-market-nav-daily-v1"
FULL_VERSION = "full-market-nav-daily-v2"


async def resolve_nav_date(
    repository: D1WriteRepository,
    *,
    target_date: str,
    today: str,
) -> dict[str, Any]:
    latest = await repository.first(
        """
        SELECT MAX(mp.trading_date) AS d
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        WHERE i.symbol='OTEC' AND mp.trading_date<=?
        """,
        (target_date,),
    )
    latest_otec_date = str(latest["d"]) if latest and latest.get("d") else None
    current_quote = await repository.first(
        """
        SELECT 1 AS ok
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        WHERE i.symbol IN ('OTEC','BMOB3') AND mp.trading_date=?
        LIMIT 1
        """,
        (target_date,),
    )
    live = target_date == today and current_quote is not None
    return {
        "latest_otec_date": latest_otec_date,
        "live_calendar_snapshot": live,
        "nav_date": target_date if live else latest_otec_date,
    }


async def _holding(repository: D1WriteRepository, as_of_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT id,shares,effective_from,effective_to
        FROM bemobi_holdings
        WHERE effective_from<=?
          AND (effective_to IS NULL OR effective_to>=?)
        ORDER BY effective_from DESC,id DESC
        LIMIT 1
        """,
        (as_of_date, as_of_date),
    )


async def _share_count(repository: D1WriteRepository, as_of_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT id,total_shares,treasury_shares,outstanding_shares,effective_from
        FROM otello_share_counts
        WHERE effective_from<=?
          AND (effective_to IS NULL OR effective_to>=?)
        ORDER BY effective_from DESC,id DESC
        LIMIT 1
        """,
        (as_of_date, as_of_date),
    )


async def rebuild_core_nav_for_date(
    repository: D1WriteRepository,
    *,
    as_of_date: str,
) -> dict[str, Any]:
    otec = await preferred_price(repository, "OTEC", as_of_date)
    bmob3 = await preferred_price(repository, "BMOB3", as_of_date)
    brl = await nearest_fx(repository, "BRL", as_of_date)
    cash = await repository.first(
        """
        SELECT estimate_date,cash_nok,quality
        FROM cash_daily_estimates
        WHERE estimate_date=?
        LIMIT 1
        """,
        (as_of_date,),
    )
    holding = await _holding(repository, as_of_date)
    shares = await _share_count(repository, as_of_date)
    missing = [
        name
        for name, value in (
            ("OTEC", otec),
            ("BMOB3", bmob3),
            ("BRL/NOK", brl),
            ("cash", cash),
            ("Bemobi holding", holding),
            ("share count", shares),
        )
        if value is None
    ]
    if missing:
        raise ValueError("Mangler CORE NAV-input: " + ", ".join(missing))

    otec_price = Decimal(str(otec["price"]))
    bmob3_price = Decimal(str(bmob3["price"]))
    brl_nok = Decimal(str(brl["rate"]))
    holding_shares = int(holding["shares"])
    cash_nok = Decimal(str(cash["cash_nok"]))
    outstanding = int(shares["outstanding_shares"])
    if outstanding <= 0:
        raise ValueError("Ugyldig antall utestående Otello-aksjer")

    bemobi_nok = Decimal(holding_shares) * bmob3_price * brl_nok
    nav_total = bemobi_nok + cash_nok
    nav_per_share = nav_total / Decimal(outstanding)
    discount = (
        (nav_per_share - otec_price) / nav_per_share
        if nav_per_share != 0
        else Decimal("0")
    )
    stale = any(
        str(item["trading_date"] if "trading_date" in item else item["rate_date"])
        != as_of_date
        for item in (otec, bmob3, brl)
    )
    status = (
        "ESTIMATED"
        if stale or str(cash["quality"]) == "FORECAST_PARTIAL"
        else "OK"
    )
    components = {
        "otec": {
            "price_id": int(otec["id"]),
            "trading_date": otec["trading_date"],
            "price_type": otec["price_type"],
            "source_code": otec["source_code"],
            "quality": otec["quality"],
        },
        "bmob3": {
            "price_id": int(bmob3["id"]),
            "trading_date": bmob3["trading_date"],
            "price_type": bmob3["price_type"],
            "source_code": bmob3["source_code"],
            "quality": bmob3["quality"],
        },
        "brl_nok": {
            "fx_rate_id": int(brl["id"]),
            "rate_date": brl["rate_date"],
        },
        "holding": {"holding_id": int(holding["id"]), "shares": holding_shares},
        "cash": {"estimate_date": cash["estimate_date"], "quality": cash["quality"]},
        "shares": {
            "share_count_id": int(shares["id"]),
            "outstanding": outstanding,
        },
    }
    inputs = {
        "date": as_of_date,
        "otec_price_id": int(otec["id"]),
        "bmob3_price_id": int(bmob3["id"]),
        "brl_nok_rate_id": int(brl["id"]),
        "holding_id": int(holding["id"]),
        "share_count_id": int(shares["id"]),
        "cash_date": cash["estimate_date"],
        "version": CORE_VERSION,
    }

    await repository.run(
        """
        INSERT INTO nav_snapshots(
            as_of_at,nav_total_nok,nav_per_share_nok,otec_price_nok,discount_pct,
            bemobi_value_nok,cash_estimate_nok,other_net_assets_nok,
            shares_outstanding,calculation_version,inputs_hash,status,
            nav_scope,components_json,quality_notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(as_of_at,calculation_version) DO UPDATE SET
            nav_total_nok=excluded.nav_total_nok,
            nav_per_share_nok=excluded.nav_per_share_nok,
            otec_price_nok=excluded.otec_price_nok,
            discount_pct=excluded.discount_pct,
            bemobi_value_nok=excluded.bemobi_value_nok,
            cash_estimate_nok=excluded.cash_estimate_nok,
            other_net_assets_nok=excluded.other_net_assets_nok,
            shares_outstanding=excluded.shares_outstanding,
            inputs_hash=excluded.inputs_hash,
            status=excluded.status,
            nav_scope=excluded.nav_scope,
            components_json=excluded.components_json,
            quality_notes=excluded.quality_notes
        """,
        (
            f"{as_of_date}T00:00:00Z",
            decimal_text(nav_total),
            decimal_text(nav_per_share),
            decimal_text(otec_price),
            decimal_text(discount),
            decimal_text(bemobi_nok),
            decimal_text(cash_nok),
            "0",
            outstanding,
            CORE_VERSION,
            stable_hash(inputs),
            status,
            "CORE",
            json.dumps(components, ensure_ascii=False, sort_keys=True),
            (
                "Market inputs may use the latest value within a seven-day lookback on non-trading days."
                if stale
                else None
            ),
        ),
    )
    return {
        "written": 1,
        "date": as_of_date,
        "nav_total_nok": decimal_text(nav_total),
        "nav_per_share_nok": decimal_text(nav_per_share),
        "status": status,
    }


async def rebuild_full_nav_for_date(
    repository: D1WriteRepository,
    *,
    as_of_date: str,
) -> dict[str, Any]:
    core = await repository.first(
        """
        SELECT id,nav_total_nok,nav_per_share_nok,otec_price_nok,discount_pct,
               bemobi_value_nok,cash_estimate_nok,shares_outstanding,status,
               components_json
        FROM nav_snapshots
        WHERE as_of_at=? AND calculation_version=? AND nav_scope='CORE'
        LIMIT 1
        """,
        (f"{as_of_date}T00:00:00Z", CORE_VERSION),
    )
    ona = await repository.first(
        """
        SELECT estimate_date,amount_nok,quality,base_amount_usd,base_amount_nok,
               associated_receivable_nok,receivable_quality,
               option_liability_nok,option_liability_usd,
               option_fair_value_per_option_nok,option_recognition_fraction,
               option_spot_nok,option_strike_nok,option_quality,option_inputs_json
        FROM other_net_assets_daily_estimates
        WHERE estimate_date=?
        LIMIT 1
        """,
        (as_of_date,),
    )
    if core is None or ona is None:
        raise ValueError("Mangler CORE NAV eller ONA for FULL NAV")

    core_total = Decimal(str(core["nav_total_nok"]))
    ona_nok = Decimal(str(ona["amount_nok"]))
    total = core_total + ona_nok
    outstanding = int(core["shares_outstanding"])
    per_share = total / Decimal(outstanding)
    otec_price = Decimal(str(core["otec_price_nok"]))
    discount = (
        (per_share - otec_price) / per_share
        if per_share != 0
        else Decimal("0")
    )
    status = str(core["status"])
    if str(ona["quality"]) == "FORECAST_PARTIAL" and status == "OK":
        status = "ESTIMATED"

    option_inputs = json.loads(str(ona.get("option_inputs_json") or "{}"))
    components = {
        "core_snapshot_id": int(core["id"]),
        "core_version": CORE_VERSION,
        "other_net_assets": {
            "estimate_date": ona["estimate_date"],
            "quality": ona["quality"],
            "base_amount_usd": ona["base_amount_usd"],
            "base_amount_nok": ona["base_amount_nok"],
            "associated_receivable_nok": ona["associated_receivable_nok"],
            "receivable_quality": ona["receivable_quality"],
            "option_liability_nok": ona["option_liability_nok"],
            "option_liability_usd": ona["option_liability_usd"],
            "option_fair_value_per_option_nok": ona["option_fair_value_per_option_nok"],
            "option_recognition_fraction": ona["option_recognition_fraction"],
            "option_spot_nok": ona["option_spot_nok"],
            "option_strike_nok": ona["option_strike_nok"],
            "option_quality": ona["option_quality"],
            "option_inputs_hash": option_inputs.get("inputs_hash"),
        },
    }
    inputs = {
        "date": as_of_date,
        "core_snapshot_id": int(core["id"]),
        "ona_date": ona["estimate_date"],
        "ona_amount_nok": ona["amount_nok"],
        "ona_option_liability_nok": ona["option_liability_nok"],
        "ona_option_inputs_hash": option_inputs.get("inputs_hash"),
        "version": FULL_VERSION,
    }

    await repository.run(
        """
        INSERT INTO nav_snapshots(
            as_of_at,nav_total_nok,nav_per_share_nok,otec_price_nok,discount_pct,
            bemobi_value_nok,cash_estimate_nok,other_net_assets_nok,
            shares_outstanding,calculation_version,inputs_hash,status,
            nav_scope,components_json,quality_notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(as_of_at,calculation_version) DO UPDATE SET
            nav_total_nok=excluded.nav_total_nok,
            nav_per_share_nok=excluded.nav_per_share_nok,
            otec_price_nok=excluded.otec_price_nok,
            discount_pct=excluded.discount_pct,
            bemobi_value_nok=excluded.bemobi_value_nok,
            cash_estimate_nok=excluded.cash_estimate_nok,
            other_net_assets_nok=excluded.other_net_assets_nok,
            shares_outstanding=excluded.shares_outstanding,
            inputs_hash=excluded.inputs_hash,
            status=excluded.status,
            nav_scope=excluded.nav_scope,
            components_json=excluded.components_json,
            quality_notes=excluded.quality_notes
        """,
        (
            f"{as_of_date}T00:00:00Z",
            decimal_text(total),
            decimal_text(per_share),
            decimal_text(otec_price),
            decimal_text(discount),
            core["bemobi_value_nok"],
            core["cash_estimate_nok"],
            decimal_text(ona_nok),
            outstanding,
            FULL_VERSION,
            stable_hash(inputs),
            status,
            "FULL",
            json.dumps(components, ensure_ascii=False, sort_keys=True),
            (
                "FULL NAV adds daily other-net-assets estimate, Bemobi receivables "
                "and option liability to CORE NAV."
            ),
        ),
    )
    return {
        "written": 1,
        "date": as_of_date,
        "nav_total_nok": decimal_text(total),
        "nav_per_share_nok": decimal_text(per_share),
        "status": status,
        "option_liability_nok": ona["option_liability_nok"],
    }


async def rebuild_dirty_nav(
    repository: D1WriteRepository,
    *,
    as_of_date: str,
) -> dict[str, Any]:
    cash = await rebuild_daily_cash_if_changed(repository, end_date=as_of_date)
    core = await rebuild_core_nav_for_date(repository, as_of_date=as_of_date)
    ona_existing = await repository.first(
        """
        SELECT estimate_date
        FROM other_net_assets_daily_estimates
        WHERE estimate_date=?
        LIMIT 1
        """,
        (as_of_date,),
    )
    if ona_existing is None:
        ona = await rebuild_other_net_assets_for_date(repository, as_of_date=as_of_date)
    else:
        ona = {
            "written": 0,
            "skipped": True,
            "reason": "ona_already_exists",
            "date": as_of_date,
        }
    full = await rebuild_full_nav_for_date(repository, as_of_date=as_of_date)
    return {
        "status": "ok",
        "date": as_of_date,
        "cash": cash,
        "core": core,
        "ona": ona,
        "full": full,
    }

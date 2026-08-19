from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.economic_nav import (
    _cash_fx_revaluation,
    _latest_cost_anchors,
    _nearest_fx,
    _option_values,
)
from app.nav.daily_nav import calculate_daily_core_nav
from app.nav_waterfall import (
    FULL_CALCULATION_VERSION,
    _components,
    _full_row,
    _modeled_buyback_cash,
    build_nav_waterfall,
)


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _synthesized_option_values(ona: Any) -> tuple[Decimal, Decimal] | None:
    accounting = Decimal(str(ona["option_liability_nok"] or "0"))
    inputs = _json_object(ona["option_inputs_json"])
    gross_raw = inputs.get("gross_fair_value_nok")
    if gross_raw is None:
        fair_raw = ona["option_fair_value_per_option_nok"]
        count_raw = inputs.get("option_count")
        if fair_raw is not None and count_raw is not None:
            gross_raw = Decimal(str(fair_raw)) * Decimal(str(count_raw))
    if gross_raw is None:
        if accounting == 0:
            return Decimal("0"), Decimal("0")
        return None
    return accounting, Decimal(str(gross_raw))


def _synthesize_report_anchor(connection, anchor_date: str):
    core = calculate_daily_core_nav(connection, anchor_date)
    if not core.get("ready"):
        return None, None, {
            "ready": False,
            "reason": "missing_anchor_core_inputs",
            "anchor_date": anchor_date,
            "missing": core.get("missing") or [],
        }

    ona = connection.execute(
        """
        SELECT estimate_date, amount_nok, quality,
               option_liability_nok, option_liability_usd,
               option_fair_value_per_option_nok, option_recognition_fraction,
               option_spot_nok, option_strike_nok, option_quality, option_inputs_json
        FROM other_net_assets_daily_estimates
        WHERE estimate_date = ?
        LIMIT 1
        """,
        (anchor_date,),
    ).fetchone()
    if ona is None:
        return None, None, {
            "ready": False,
            "reason": "missing_anchor_other_net_assets",
            "anchor_date": anchor_date,
        }

    option_values = _synthesized_option_values(ona)
    if option_values is None:
        return None, None, {
            "ready": False,
            "reason": "missing_anchor_option_values",
            "anchor_date": anchor_date,
        }

    ona_nok = Decimal(str(ona["amount_nok"]))
    nav_total = Decimal(str(core["nav_total_nok"])) + ona_nok
    shares = int(core["shares_outstanding"])
    core_components = core.get("components") or {}
    bmob3 = core_components.get("bmob3") or {}
    otec = core_components.get("otec") or {}
    cash = core_components.get("cash") or {}

    return (
        {
            "as_of_at": f"{anchor_date}T23:59:59Z",
            "nav_total_nok": nav_total,
            "nav_per_share_nok": nav_total / Decimal(shares),
            "bemobi_value_nok": core["bemobi_value_nok"],
            "cash_estimate_nok": core["cash_nok"],
            "other_net_assets_nok": ona_nok,
            "shares_outstanding": shares,
            "status": "SYNTHESIZED_REPORT_ANCHOR",
        },
        option_values,
        {
            "ready": True,
            "mode": "SYNTHESIZED_REPORT_ANCHOR",
            "report_date": anchor_date,
            "bmob3_market_date": bmob3.get("price_date"),
            "otec_market_date": otec.get("price_date"),
            "brl_nok_date": bmob3.get("brl_nok_date"),
            "cash_quality": cash.get("quality"),
            "ona_quality": ona["quality"],
            "note": (
                "Rapportankeret er rekonstruert på rapportdatoen fra kildebelagt cash/ONA/aksjetall. "
                "Markedspriser og valuta bruker siste tilgjengelige observasjon på eller før rapportdatoen."
            ),
        },
    )


def _resolve_anchor(connection, anchor_date: str):
    stored = _full_row(connection, anchor_date)
    if stored is not None:
        option_values = _option_values(_components(stored["components_json"]))
        if option_values is None:
            return None, None, {
                "ready": False,
                "reason": "missing_anchor_option_values",
                "anchor_date": anchor_date,
            }
        return stored, option_values, {
            "ready": True,
            "mode": "STORED_FULL_SNAPSHOT",
            "report_date": anchor_date,
        }
    return _synthesize_report_anchor(connection, anchor_date)


def nav_waterfall_summary(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        latest = connection.execute(
            """
            SELECT MAX(substr(as_of_at,1,10)) AS max_date
            FROM nav_snapshots
            WHERE calculation_version=? AND nav_scope='FULL'
            """,
            (FULL_CALCULATION_VERSION,),
        ).fetchone()
        as_of_date = latest["max_date"] if latest is not None else None
        if as_of_date is None:
            return {"ready": False, "reason": "missing_full_nav"}

        anchor = connection.execute(
            """
            SELECT as_of_date FROM cash_anchors
            WHERE anchor_type='REPORTED' AND as_of_date <= ?
            ORDER BY as_of_date DESC, id DESC LIMIT 1
            """,
            (as_of_date,),
        ).fetchone()
        if anchor is None:
            return {"ready": False, "reason": "missing_reported_cash_anchor"}
        anchor_date = str(anchor["as_of_date"])

        current = _full_row(connection, str(as_of_date))
        if current is None:
            return {"ready": False, "reason": "missing_current_full_nav"}

        anchor_row, anchor_options, anchor_resolution = _resolve_anchor(connection, anchor_date)
        if anchor_row is None or anchor_options is None:
            return anchor_resolution

        current_options = _option_values(_components(current["components_json"]))
        if current_options is None:
            return {"ready": False, "reason": "missing_option_values"}
        current_accounting_option, current_economic_option = current_options
        anchor_accounting_option, anchor_economic_option = anchor_options

        cash_fx = _cash_fx_revaluation(
            connection,
            cash_anchor_date=anchor_date,
            as_of_date=str(as_of_date),
        )
        if not cash_fx.get("ready"):
            return cash_fx

        usd_nok = _nearest_fx(connection, "USD", str(as_of_date))
        if usd_nok is None:
            return {"ready": False, "reason": "missing_recent_usd_nok"}
        cost_anchors = _latest_cost_anchors(connection, str(as_of_date))
        base_cost = cost_anchors.get("BASE")
        if base_cost is None:
            return {"ready": False, "reason": "missing_operating_cost_anchor"}
        days_since_anchor = max(
            0,
            (date.fromisoformat(str(as_of_date)) - date.fromisoformat(anchor_date)).days,
        )
        operating_cost_nok = (
            base_cost["amount_usd_decimal"]
            / Decimal(base_cost["period_days_int"])
            * Decimal(days_since_anchor)
            * Decimal(str(usd_nok["rate"]))
        )

        buybacks = _modeled_buyback_cash(
            connection,
            anchor_date=anchor_date,
            as_of_date=str(as_of_date),
        )

        result = build_nav_waterfall(
            anchor_date=anchor_date,
            as_of_date=str(as_of_date),
            anchor_nav_total_nok=Decimal(str(anchor_row["nav_total_nok"])),
            anchor_bemobi_value_nok=Decimal(str(anchor_row["bemobi_value_nok"])),
            anchor_cash_nok=Decimal(str(anchor_row["cash_estimate_nok"])),
            anchor_other_net_assets_nok=Decimal(str(anchor_row["other_net_assets_nok"])),
            anchor_shares_outstanding=int(anchor_row["shares_outstanding"]),
            anchor_accounting_option_nok=anchor_accounting_option,
            anchor_economic_option_nok=anchor_economic_option,
            current_nav_total_nok=Decimal(str(current["nav_total_nok"])),
            current_bemobi_value_nok=Decimal(str(current["bemobi_value_nok"])),
            current_cash_nok=Decimal(str(current["cash_estimate_nok"])),
            current_other_net_assets_nok=Decimal(str(current["other_net_assets_nok"])),
            current_shares_outstanding=int(current["shares_outstanding"]),
            current_accounting_option_nok=current_accounting_option,
            current_economic_option_nok=current_economic_option,
            buyback_cash_nok=buybacks["amount_nok"],
            cash_fx_adjustment_nok=Decimal(str(cash_fx["adjustment_nok"])),
            operating_cost_nok=operating_cost_nok,
            buyback_movement_count=int(buybacks["movement_count"]),
            cross_anchor_buybacks_excluded=int(buybacks["cross_anchor_excluded"]),
        )
        if result.get("ready"):
            result["anchor_resolution"] = anchor_resolution
        return result

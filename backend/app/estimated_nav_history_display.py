from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.estimated_nav_history import _cash_breakdown, estimated_nav_history as _estimated_nav_history
from app.life360_nav import _life360_holding, life360_nav_adjustment
from app.option_settlement import MILLION

TOLERANCE_NOK = Decimal("1000")
ALLIANCE_VENTURE_SPRING_SHARES = 7_411_532


def _display_date(value: str) -> str:
    """Formater en ISO-dato for norsk visningstekst."""
    try:
        return date.fromisoformat(value).strftime("%d.%m.%Y")
    except ValueError:
        return value


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _format_share_count(value: Any) -> str:
    return f"{int(value or 0):,}".replace(",", " ")


def _item(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((item for item in items if str(item.get("key")) == key), None)


def _component(
    key: str,
    label: str,
    amount_nok: Decimal,
    shares: int,
    formula: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "amount_mnok": float(amount_nok / MILLION),
        "per_share_nok": float(amount_nok / Decimal(shares)),
        "formula": formula,
        "details": details or {},
    }


def _state_details(state: dict[str, Any]) -> dict[str, Any]:
    ready = bool(state.get("ready"))
    return {
        "active": ready,
        "display_available": ready,
        "reason": state.get("reason"),
        "shares": state.get("shares"),
        "anchor_shares": state.get("anchor_shares"),
        "holding_effective_from": state.get("holding_effective_from"),
        "holding_effective_to": state.get("holding_effective_to"),
        "holding_quality": state.get("holding_quality"),
        "holding_basis": state.get("holding_basis"),
        "holding_source_document_id": state.get("holding_source_document_id"),
        "holding_source_locator": state.get("holding_source_locator"),
        "anchor_holding_effective_from": state.get("anchor_holding_effective_from"),
        "anchor_holding_effective_to": state.get("anchor_holding_effective_to"),
        "anchor_holding_quality": state.get("anchor_holding_quality"),
        "anchor_holding_basis": state.get("anchor_holding_basis"),
        "anchor_holding_source_document_id": state.get("anchor_holding_source_document_id"),
        "price_usd": None if state.get("price") is None else float(_decimal(state.get("price"))),
        "price_date": state.get("price_date"),
        "price_source": state.get("price_source"),
        "fx_usd_nok": None if state.get("fx_rate") is None else float(_decimal(state.get("fx_rate"))),
        "fx_date": state.get("fx_date"),
        "anchor_date": state.get("anchor_date"),
        "anchor_price_usd": None if state.get("anchor_price_usd") is None else float(_decimal(state.get("anchor_price_usd"))),
        "anchor_price_date": state.get("anchor_price_date"),
        "market_value_mnok": None if not ready else float(_decimal(state.get("market_value_nok")) / MILLION),
        "embedded_value_mnok": None if not ready else float(_decimal(state.get("embedded_value_nok")) / MILLION),
        "adjustment_mnok": None if not ready else float(_decimal(state.get("adjustment_nok")) / MILLION),
        "display_basis": "GROSS_MARKET_VALUE_EX_OONA" if ready else "UNAVAILABLE",
    }


def _confirmed_other_cash_display(
    rows: list[dict[str, Any]],
    expected_nok: Decimal,
) -> tuple[bool, str, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    total_nok = Decimal("0")
    for row in rows:
        amount_nok = _decimal(row.get("amount_nok"))
        amount_original = _decimal(row.get("amount_original"))
        total_nok += amount_nok
        events.append(
            {
                "movement_date": str(row.get("movement_date") or ""),
                "movement_type": str(row.get("movement_type") or ""),
                "amount_nok": float(amount_nok),
                "amount_original": float(amount_original),
                "currency": str(row.get("currency") or ""),
                "description": str(row.get("description") or ""),
                "external_movement_id": str(row.get("external_movement_id") or ""),
                "source_document_id": row.get("source_document_id"),
            }
        )

    reconciles = bool(events) and abs(total_nok - expected_nok) <= TOLERANCE_NOK
    if not reconciles:
        return False, "Kjente kontantbevegelser utenom tilbakekjøp", events
    if len(events) != 1:
        return True, f"{len(events)} bekreftede kontantbevegelser siden siste rapport", events

    event = events[0]
    event_date = str(event["movement_date"])
    display_date = _display_date(event_date)
    external_id = str(event["external_movement_id"])
    event_name = (
        "Patentoppgjør"
        if external_id.startswith("otello-report-post-cash:PATENT_SALE_FINAL_INSTALMENT:")
        else "Bekreftet kontantbevegelse"
    )
    amount_original = _decimal(event["amount_original"])
    amount_text = f"{amount_original / MILLION:.2f}".replace(".", ",").rstrip("0").rstrip(",")
    currency = str(event["currency"] or "")
    return True, f"{event_name} {display_date}: {currency} {amount_text}m", events


def _report_split_state(database_path: str | None, report_date: str) -> dict[str, Any]:
    """Resolve the latest source-backed investment report anchor at or before cash report date."""
    if not report_date:
        return {"ready": False, "reason": "missing_report_date"}
    with get_connection(database_path) as connection:
        cash = connection.execute(
            """
            SELECT id, as_of_date, amount_nok, reported_amount, reported_currency,
                   fx_rate_to_nok, source_document_id
            FROM cash_anchors
            WHERE anchor_type='REPORTED' AND as_of_date=?
            ORDER BY id DESC LIMIT 1
            """,
            (report_date,),
        ).fetchone()
        ona = connection.execute(
            """
            SELECT r.id AS reported_anchor_id, r.as_of_date,
                   r.base_other_net_assets_ex_option_reported,
                   r.other_shares_investment_reported,
                   r.source_document_id, n.fx_rate_to_nok
            FROM other_net_assets_reported_anchors r
            JOIN other_net_assets_anchors n ON n.reported_anchor_id=r.id
            WHERE r.as_of_date<=?
              AND r.other_shares_investment_reported IS NOT NULL
            ORDER BY r.as_of_date DESC, r.id DESC, n.id DESC LIMIT 1
            """,
            (report_date,),
        ).fetchone()
        if cash is None:
            return {"ready": False, "reason": "missing_reported_cash_anchor", "report_date": report_date}
        if ona is None:
            return {"ready": False, "reason": "missing_reported_investment_anchor", "report_date": report_date}

        resolved_report_date = str(ona["as_of_date"])
        floor = (date.fromisoformat(resolved_report_date) - timedelta(days=7)).isoformat()
        lif = connection.execute(
            """
            SELECT mp.trading_date, mp.price, mp.quality, s.code AS source_code
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            JOIN sources s ON s.id=mp.source_id
            WHERE i.symbol='LIF' AND mp.currency='USD'
              AND mp.price_type IN ('CLOSE','LAST')
              AND mp.trading_date<=? AND mp.trading_date>=?
            ORDER BY mp.trading_date DESC,
                     CASE s.code WHEN 'YAHOO_FINANCE' THEN 0 WHEN 'LIFE360_IR_LSEG' THEN 1 ELSE 5 END,
                     CASE mp.price_type WHEN 'CLOSE' THEN 0 ELSE 1 END,
                     mp.observed_at DESC, mp.id DESC
            LIMIT 1
            """,
            (resolved_report_date, floor),
        ).fetchone()
        holding = _life360_holding(connection, resolved_report_date)

    if lif is None:
        return {
            "ready": False,
            "reason": "missing_report_date_lif_price",
            "report_date": report_date,
            "resolved_report_anchor_date": resolved_report_date,
        }
    if holding is None:
        return {
            "ready": False,
            "reason": "missing_report_date_life360_holding",
            "report_date": report_date,
            "resolved_report_anchor_date": resolved_report_date,
        }

    report_fx = _decimal(ona["fx_rate_to_nok"])
    base_ex_option_usd = _decimal(ona["base_other_net_assets_ex_option_reported"])
    other_shares_usd = _decimal(ona["other_shares_investment_reported"])
    life360_price_usd = _decimal(lif["price"])
    life360_report_shares = int(holding["shares"])
    life360_report_usd = Decimal(life360_report_shares) * life360_price_usd
    alliance_report_usd = other_shares_usd - life360_report_usd
    residual_report_usd = base_ex_option_usd - other_shares_usd
    if report_fx <= 0:
        return {"ready": False, "reason": "invalid_report_usd_nok", "report_date": report_date}
    if other_shares_usd <= 0:
        return {"ready": False, "reason": "invalid_reported_other_shares", "report_date": report_date}
    if alliance_report_usd < 0:
        return {
            "ready": False,
            "reason": "alliance_report_residual_negative",
            "report_date": report_date,
            "resolved_report_anchor_date": resolved_report_date,
            "other_shares_usd": str(other_shares_usd),
            "life360_report_usd": str(life360_report_usd),
        }

    return {
        "ready": True,
        "report_date": report_date,
        "resolved_report_anchor_date": resolved_report_date,
        "source_document_id": ona["source_document_id"],
        "cash_source_document_id": cash["source_document_id"],
        "reported_cash_nok": _decimal(cash["amount_nok"]),
        "reported_cash_original": _decimal(cash["reported_amount"]),
        "reported_cash_currency": cash["reported_currency"],
        "report_usd_nok": report_fx,
        "base_other_net_assets_ex_option_usd": base_ex_option_usd,
        "other_shares_investment_usd": other_shares_usd,
        "life360_report_shares": life360_report_shares,
        "life360_holding_effective_from": str(holding["effective_from"]),
        "life360_holding_effective_to": holding.get("effective_to"),
        "life360_holding_quality": str(holding["quality"]),
        "life360_holding_basis": str(holding["basis"]),
        "life360_holding_source_document_id": holding.get("source_document_id"),
        "life360_holding_source_locator": holding.get("source_locator"),
        "life360_report_price_usd": life360_price_usd,
        "life360_report_price_date": str(lif["trading_date"]),
        "life360_report_price_source": str(lif["source_code"]),
        "life360_report_usd": life360_report_usd,
        "life360_report_nok": life360_report_usd * report_fx,
        "alliance_report_usd": alliance_report_usd,
        "alliance_report_nok": alliance_report_usd * report_fx,
        "residual_report_usd": residual_report_usd,
        "residual_report_nok": residual_report_usd * report_fx,
    }


def _split_current_composition(
    database_path: str | None,
    point: dict[str, Any],
    life360_state: dict[str, Any],
) -> bool:
    composition = point.get("composition") or []
    if not isinstance(composition, list):
        return False
    cash = _item(composition, "cash")
    ona = _item(composition, "ona")
    life360 = _item(composition, "life360")
    bemobi = _item(composition, "bemobi")
    options = _item(composition, "options")
    if any(item is None for item in (cash, ona, life360, bemobi, options)):
        return False

    shares = int(point.get("shares_outstanding") or 0)
    if shares <= 0:
        return False
    current_date = str(point.get("date") or "")
    cash_details = dict(cash.get("details") or {})
    cash_report_date = str(cash_details.get("cash_anchor_date") or "")
    report = _report_split_state(database_path, cash_report_date)
    if not report.get("ready"):
        point["composition_split_status"] = report
        return False

    state_reason = str(life360_state.get("reason") or "")
    if "life360_holding" in state_reason:
        point["composition_split_status"] = {
            "ready": False,
            "reason": state_reason,
            "current_date": current_date,
        }
        return False

    investment_report_date = str(report["resolved_report_anchor_date"])
    modeled_cash_nok = _decimal(cash_details.get("reported_cash_mnok")) * MILLION
    cash_fx_nok = _decimal(cash_details.get("cash_fx_adjustment_mnok")) * MILLION
    operating_cost_nok = _decimal(cash_details.get("operating_cost_mnok")) * MILLION
    old_cash_nok = _decimal(cash.get("amount_mnok")) * MILLION
    if abs(old_cash_nok - (modeled_cash_nok + cash_fx_nok - operating_cost_nok)) > TOLERANCE_NOK:
        point["composition_split_status"] = {"ready": False, "reason": "cash_split_does_not_reconcile"}
        return False

    with get_connection(database_path) as connection:
        cash_movements = _cash_breakdown(
            connection,
            start_date=cash_report_date,
            current_date=current_date,
        )
        confirmed_other_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT movement_date, movement_type, amount_nok, amount_original, currency,
                       description, external_movement_id, source_document_id
                FROM cash_movements
                WHERE movement_date > ? AND movement_date <= ?
                  AND movement_type='OTHER' AND confidence='CONFIRMED'
                ORDER BY movement_date, id
                """,
                (cash_report_date, current_date),
            ).fetchall()
        ]
    buyback_nok = _decimal(cash_movements.get("buyback_cash_nok"))
    reported_cash_nok = _decimal(report["reported_cash_nok"])
    other_cash_nok = modeled_cash_nok - reported_cash_nok - buyback_nok
    other_cash_confirmed, other_cash_formula, confirmed_other_events = _confirmed_other_cash_display(
        confirmed_other_rows,
        other_cash_nok,
    )

    old_ona_nok = _decimal(ona.get("amount_mnok")) * MILLION
    old_life360_adjustment_nok = _decimal(life360.get("amount_mnok")) * MILLION
    alliance_report_nok = _decimal(report["alliance_report_nok"])
    residual_report_nok = _decimal(report["residual_report_nok"])

    state_details = _state_details(life360_state)
    if life360_state.get("ready"):
        expected_adjustment = _decimal(life360_state.get("adjustment_nok"))
        if abs(old_life360_adjustment_nok - expected_adjustment) > TOLERANCE_NOK:
            point["composition_split_status"] = {
                "ready": False,
                "reason": "life360_adjustment_does_not_reconcile",
            }
            return False
        life360_nok = _decimal(life360_state.get("market_value_nok"))
        life360_label = "Life360 mark-to-market"
        life360_formula = (
            f"{_format_share_count(life360_state.get('shares'))} LIF-aksjer × siste LIF-kurs × USD/NOK"
        )
        state_details["display_basis"] = "CURRENT_MARKET_VALUE"
    else:
        life360_nok = _decimal(report["life360_report_nok"])
        life360_label = "Life360 – siste rapportverdi"
        life360_formula = (
            f"{_format_share_count(report['life360_report_shares'])} LIF-aksjer × "
            "LIF-kurs på rapportdato × rapportdatoens USD/NOK"
        )
        state_details.update(
            {
                "active": False,
                "display_available": True,
                "mark_to_market_available": False,
                "display_basis": "LAST_REPORTED_VALUE_FALLBACK",
                "report_date": investment_report_date,
                "report_value_mnok": float(life360_nok / MILLION),
                "report_price_usd": float(_decimal(report["life360_report_price_usd"])),
                "report_price_date": report["life360_report_price_date"],
                "report_price_source": report["life360_report_price_source"],
            }
        )

    ona_and_life_nok = old_ona_nok + old_life360_adjustment_nok
    ona_currency_effect_nok = (
        ona_and_life_nok
        - alliance_report_nok
        - residual_report_nok
        - life360_nok
    )
    currency_effect_nok = cash_fx_nok + ona_currency_effect_nok
    cash_report_display_date = _display_date(cash_report_date)
    current_display_date = _display_date(current_date)

    new_components: list[dict[str, Any]] = [dict(bemobi)]
    new_components.extend(
        [
            _component(
                "reported_cash",
                "Kontantbeholdning",
                reported_cash_nok,
                shares,
                f"Siste rapporterte kontantbeholdning ({cash_report_display_date})",
                {
                    "report_date": cash_report_date,
                    "source_document_id": report.get("cash_source_document_id"),
                    "reported_currency": report.get("reported_cash_currency"),
                    "reported_amount": float(_decimal(report.get("reported_cash_original"))),
                    "display_policy": "FIXED_AT_LAST_REPORT",
                },
            ),
            _component(
                "operating_cost_since_report",
                "Estimert drift siden siste rapport",
                -operating_cost_nok,
                shares,
                "Estimert løpende drift fra "
                f"{cash_report_display_date} til {current_display_date}",
                {"report_date": cash_report_date, "current_date": current_date},
            ),
            _component(
                "buybacks_since_report",
                "Tilbakekjøp siden siste rapport",
                buyback_nok,
                shares,
                f"Kontantbruk på egne aksjer etter {cash_report_display_date}",
                {
                    "report_date": cash_report_date,
                    "current_date": current_date,
                    "daily_rows": cash_movements.get("daily_buyback_rows"),
                    "weekly_rows": cash_movements.get("weekly_buyback_rows"),
                    "weekly_rows_superseded": cash_movements.get("weekly_buyback_rows_superseded"),
                },
            ),
        ]
    )
    if abs(other_cash_nok) > TOLERANCE_NOK:
        new_components.append(
            _component(
                "other_cash_since_report",
                (
                    "Bekreftede øvrige kontantbevegelser"
                    if other_cash_confirmed
                    else "Andre kontantbevegelser siden siste rapport"
                ),
                other_cash_nok,
                shares,
                other_cash_formula,
                {
                    "report_date": cash_report_date,
                    "current_date": current_date,
                    "confirmed": other_cash_confirmed,
                    "confirmed_events": confirmed_other_events,
                },
            )
        )
    if abs(currency_effect_nok) > TOLERANCE_NOK:
        new_components.append(
            _component(
                "fx_since_report",
                "Valutaeffekt siden siste rapport",
                currency_effect_nok,
                shares,
                "Valutaeffekt siden rapport på rapportert cash og USD-baserte investeringsposter",
                {
                    "cash_fx_mnok": float(cash_fx_nok / MILLION),
                    "investment_fx_mnok": float(ona_currency_effect_nok / MILLION),
                    "cash_report_date": cash_report_date,
                    "investment_report_date": investment_report_date,
                },
            )
        )

    new_components.append(
        _component(
            "alliance_venture_spring",
            "Alliance Venture Spring AS",
            alliance_report_nok,
            shares,
            "7 411 532 aksjer – fair value fra siste rapport, holdes fast til neste rapport",
            {
                "shares": ALLIANCE_VENTURE_SPRING_SHARES,
                "report_date": investment_report_date,
                "report_value_usd": float(_decimal(report["alliance_report_usd"])),
                "report_usd_nok": float(_decimal(report["report_usd_nok"])),
                "other_shares_investment_usd": float(_decimal(report["other_shares_investment_usd"])),
                "life360_report_shares": report["life360_report_shares"],
                "life360_holding_effective_from": report["life360_holding_effective_from"],
                "life360_holding_source_document_id": report["life360_holding_source_document_id"],
                "derivation": "REPORTED_OTHER_SHARES_MINUS_REPORT_DATE_LIFE360_VALUE",
                "display_policy": "FIXED_AT_LAST_REPORT",
                "source_document_id": report.get("source_document_id"),
            },
        )
    )
    if abs(residual_report_nok) > TOLERANCE_NOK:
        new_components.append(
            _component(
                "other_reported_assets_liabilities",
                "Andre rapporterte eiendeler og forpliktelser",
                residual_report_nok,
                shares,
                "Rapportert ONA ekskl. opsjoner minus Investments in other shares",
                {
                    "report_date": investment_report_date,
                    "report_value_usd": float(_decimal(report["residual_report_usd"])),
                    "display_policy": "FIXED_AT_LAST_REPORT",
                    "source_document_id": report.get("source_document_id"),
                },
            )
        )
    new_components.extend(
        [
            _component(
                "life360",
                life360_label,
                life360_nok,
                shares,
                life360_formula,
                {
                    **state_details,
                    "report_date": investment_report_date,
                    "report_shares": report["life360_report_shares"],
                    "report_holding_effective_from": report["life360_holding_effective_from"],
                    "report_holding_effective_to": report["life360_holding_effective_to"],
                    "report_holding_quality": report["life360_holding_quality"],
                    "report_holding_basis": report["life360_holding_basis"],
                    "report_holding_source_document_id": report["life360_holding_source_document_id"],
                    "report_holding_source_locator": report["life360_holding_source_locator"],
                    "report_value_mnok": float(_decimal(report["life360_report_nok"]) / MILLION),
                },
            ),
            dict(options),
        ]
    )

    old_total_nok = sum((_decimal(item.get("amount_mnok")) * MILLION for item in composition), Decimal("0"))
    new_total_nok = sum((_decimal(item.get("amount_mnok")) * MILLION for item in new_components), Decimal("0"))
    if abs(old_total_nok - new_total_nok) > TOLERANCE_NOK:
        point["composition_split_status"] = {
            "ready": False,
            "reason": "display_composition_does_not_reconcile",
            "residual_nok": float(old_total_nok - new_total_nok),
        }
        return False

    point["composition"] = new_components
    point["composition_split_status"] = {
        "ready": True,
        "cash_report_date": cash_report_date,
        "investment_report_date": investment_report_date,
        "anchor_fallback_used": investment_report_date != cash_report_date,
        "policy": "REPORT_CASH_ALLIANCE_AND_RESIDUAL_WITH_EXPLICIT_MOVEMENTS_AND_FX",
    }
    return True


def _enrich_change(
    change: dict[str, Any],
    start_state: dict[str, Any],
    current_state: dict[str, Any],
) -> None:
    drivers = change.get("drivers") or []
    if not isinstance(drivers, list):
        return
    life360 = _item(drivers, "life360")
    other_ona = _item(drivers, "other_ona")
    if life360 is None:
        return
    life360["label"] = "Life 360"

    both_ready = bool(start_state.get("ready") and current_state.get("ready"))
    life360["details"] = {
        **(life360.get("details") or {}),
        "display_available": both_ready,
        "start_active": bool(start_state.get("ready")),
        "current_active": bool(current_state.get("ready")),
        "start_reason": start_state.get("reason"),
        "current_reason": current_state.get("reason"),
        "start_market_value_mnok": None if not start_state.get("ready") else float(_decimal(start_state.get("market_value_nok")) / MILLION),
        "current_market_value_mnok": None if not current_state.get("ready") else float(_decimal(current_state.get("market_value_nok")) / MILLION),
        "start_embedded_value_mnok": None if not start_state.get("ready") else float(_decimal(start_state.get("embedded_value_nok")) / MILLION),
        "current_embedded_value_mnok": None if not current_state.get("ready") else float(_decimal(current_state.get("embedded_value_nok")) / MILLION),
        "start_price_usd": None if not start_state.get("ready") else float(_decimal(start_state.get("price"))),
        "current_price_usd": None if not current_state.get("ready") else float(_decimal(current_state.get("price"))),
        "start_usd_nok": None if not start_state.get("ready") else float(_decimal(start_state.get("fx_rate"))),
        "current_usd_nok": None if not current_state.get("ready") else float(_decimal(current_state.get("fx_rate"))),
    }
    if not both_ready:
        return

    old_life_delta_nok = _decimal(life360.get("amount_mnok")) * MILLION
    start_market_nok = _decimal(start_state.get("market_value_nok"))
    current_market_nok = _decimal(current_state.get("market_value_nok"))
    gross_delta_nok = current_market_nok - start_market_nok
    reallocation_nok = gross_delta_nok - old_life_delta_nok

    share_change = change.get("share_count_change") or {}
    start_shares = int(share_change.get("start_shares") or 0)
    current_shares = int(share_change.get("current_shares") or 0)
    if start_shares <= 0 or current_shares <= 0:
        life360["details"] = {
            **life360["details"],
            "display_available": False,
            "reason": "invalid_share_count",
        }
        return
    reciprocal_scale = (
        Decimal("1") / Decimal(start_shares)
        + Decimal("1") / Decimal(current_shares)
    ) / Decimal("2")
    holding = Decimal(int(current_state.get("shares") or 0))
    start_price = _decimal(start_state.get("price"))
    current_price = _decimal(current_state.get("price"))
    start_fx = _decimal(start_state.get("fx_rate"))
    current_fx = _decimal(current_state.get("fx_rate"))
    price_effect_nok = (
        holding
        * (current_price - start_price)
        * (start_fx + current_fx)
        / Decimal("2")
    )
    fx_effect_nok = gross_delta_nok - price_effect_nok

    life360["amount_mnok"] = float(gross_delta_nok / MILLION)
    life360["per_share_nok"] = float(gross_delta_nok * reciprocal_scale)
    life360["details"] = {
        **life360["details"],
        "start_amount_mnok": float(start_market_nok / MILLION),
        "current_amount_mnok": float(current_market_nok / MILLION),
        "display_basis": "GROSS_MARKET_VALUE_CHANGE",
        "price_effect_mnok": float(price_effect_nok / MILLION),
        "price_effect_per_share_nok": float(price_effect_nok * reciprocal_scale),
        "fx_effect_mnok": float(fx_effect_nok / MILLION),
        "fx_effect_per_share_nok": float(fx_effect_nok * reciprocal_scale),
    }

    if other_ona is not None:
        other_ona_nok = _decimal(other_ona.get("amount_mnok")) * MILLION - reallocation_nok
        other_ona["amount_mnok"] = float(other_ona_nok / MILLION)
        other_ona["per_share_nok"] = float(
            _decimal(other_ona.get("per_share_nok")) - reallocation_nok * reciprocal_scale
        )
        other_ona["details"] = {
            **(other_ona.get("details") or {}),
            "life360_embedded_reallocation_mnok": float(reallocation_nok / MILLION),
        }


def estimated_nav_history(database_path: str | None = None, *, days: int) -> dict[str, Any]:
    """Reference presentation for the investor-facing Estimert NAV composition."""
    result = deepcopy(_estimated_nav_history(database_path, days=days))
    if not result.get("ready"):
        return result

    current = result.get("current") or {}
    current_date = str(current.get("date") or result.get("to") or "")
    current_state = (
        life360_nav_adjustment(as_of_date=current_date, database_path=database_path)
        if current_date
        else {"ready": False, "reason": "missing_current_date"}
    )
    split_ready = False
    if current:
        split_ready = _split_current_composition(database_path, current, current_state)

    change = result.get("change") or {}
    if change.get("ready"):
        start_date = str(change.get("resolved_start") or "")
        end_date = str(change.get("current_date") or current_date)
        start_state = (
            life360_nav_adjustment(as_of_date=start_date, database_path=database_path)
            if start_date
            else {"ready": False, "reason": "missing_start_date"}
        )
        end_state = current_state if end_date == current_date else (
            life360_nav_adjustment(as_of_date=end_date, database_path=database_path)
            if end_date
            else {"ready": False, "reason": "missing_current_date"}
        )
        _enrich_change(change, start_state, end_state)

    result["life360_display_policy"] = "GROSS_MARKET_VALUE_WITH_REPORTED_VALUE_FALLBACK"
    result["composition_display_policy"] = (
        "REPORT_CASH_ALLIANCE_AND_RESIDUAL_WITH_EXPLICIT_MOVEMENTS_AND_FX"
        if split_ready
        else "LEGACY_COMPOSITION_FAIL_CLOSED"
    )
    return result

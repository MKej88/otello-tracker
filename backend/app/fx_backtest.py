from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection

MAX_FX_LOOKBACK_DAYS = 7
SUPPORTED_CURRENCIES = {"NOK", "USD", "BRL"}


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _float(value: Decimal | str | int | float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


def _nearest_fx(connection, base: str, day: str):
    floor_date = (date.fromisoformat(day) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT substr(observed_at,1,10) AS rate_date, rate
        FROM fx_rates
        WHERE base_currency=? AND quote_currency='NOK'
          AND substr(observed_at,1,10) <= ? AND substr(observed_at,1,10) >= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1
        """,
        (base, day, floor_date),
    ).fetchone()


def _anchors(connection) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, metadata_json FROM source_documents
        WHERE document_type='ECONOMIC_NAV_CASH_FX_ANCHOR'
        ORDER BY id DESC
        """
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        anchor_date = str(metadata.get("as_of_date") or "")[:10]
        if anchor_date and anchor_date not in result:
            result[anchor_date] = {**metadata, "source_document_id": int(row["id"])}
    return result


def _outcomes(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, metadata_json FROM source_documents
        WHERE document_type='ECONOMIC_NAV_FX_BACKTEST_OUTCOME'
        ORDER BY id DESC
        """
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        period_end = str(metadata.get("period_end") or "")[:10]
        if period_end and period_end not in result:
            result[period_end] = {**metadata, "source_document_id": int(row["id"])}
    return sorted(result.values(), key=lambda item: str(item["period_end"]))


def _rates(connection, day: str) -> tuple[Decimal, Decimal, str, str] | None:
    usd = _nearest_fx(connection, "USD", day)
    brl = _nearest_fx(connection, "BRL", day)
    if usd is None or brl is None:
        return None
    return (
        Decimal(str(usd["rate"])),
        Decimal(str(brl["rate"])),
        str(usd["rate_date"]),
        str(brl["rate_date"]),
    )


def _value_usd(balances: dict[str, Decimal], usd_nok: Decimal, brl_nok: Decimal) -> Decimal:
    return (
        balances["USD"]
        + balances["NOK"] / usd_nok
        + balances["BRL"] * brl_nok / usd_nok
    )


def _initial_balances(anchor: dict[str, Any], usd_nok: Decimal, brl_nok: Decimal) -> dict[str, Decimal]:
    balances = {"NOK": Decimal("0"), "USD": Decimal("0"), "BRL": Decimal("0")}
    for item in anchor.get("exposures") or []:
        currency = str(item.get("currency") or "").upper()
        usd_equivalent = Decimal(str(item.get("usd_equivalent") or "0"))
        if currency == "USD":
            balances["USD"] += usd_equivalent
        elif currency == "BRL":
            balances["BRL"] += usd_equivalent * usd_nok / brl_nok
        elif currency in {"NOK", "UNALLOCATED"}:
            balances["NOK"] += usd_equivalent * usd_nok
    return balances


def _movements(connection, start: str, end: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT movement_date, movement_type, amount_nok, amount_original,
                   currency, fx_rate_to_nok, confidence
            FROM cash_movements
            WHERE movement_date > ? AND movement_date <= ?
              AND currency IN ('NOK','USD','BRL')
            ORDER BY movement_date, id
            """,
            (start, end),
        ).fetchall()
    ]


def _movement_original(item: dict[str, Any]) -> Decimal | None:
    raw = item.get("amount_original")
    if raw is not None:
        return Decimal(str(raw))
    amount_nok = item.get("amount_nok")
    fx = item.get("fx_rate_to_nok")
    if amount_nok is None or fx in (None, "0", 0):
        return None
    return Decimal(str(amount_nok)) / Decimal(str(fx))


def _period_backtest(connection, outcome: dict[str, Any], anchors: dict[str, dict[str, Any]]) -> dict[str, Any]:
    start = str(outcome["period_start"])[:10]
    end = str(outcome["period_end"])[:10]
    start_anchor = anchors.get(start)
    end_anchor = anchors.get(end)
    if start_anchor is None or end_anchor is None:
        return {"ready": False, "period_start": start, "period_end": end, "reason": "missing_fx_anchor"}

    start_rates = _rates(connection, start)
    end_rates = _rates(connection, end)
    if start_rates is None or end_rates is None:
        return {"ready": False, "period_start": start, "period_end": end, "reason": "missing_historical_fx_rates"}

    usd_nok, brl_nok, usd_rate_date, brl_rate_date = start_rates
    balances = _initial_balances(start_anchor, usd_nok, brl_nok)
    previous_usd_nok = usd_nok
    previous_brl_nok = brl_nok
    fx_effect = Decimal("0")
    applied_movements = 0
    skipped_movements = 0

    movements = _movements(connection, start, end)
    by_date: dict[str, list[dict[str, Any]]] = {}
    for item in movements:
        by_date.setdefault(str(item["movement_date"]), []).append(item)

    for movement_date, items in sorted(by_date.items()):
        current_rates = _rates(connection, movement_date)
        if current_rates is None:
            skipped_movements += len(items)
            continue
        current_usd_nok, current_brl_nok, _, _ = current_rates
        before = _value_usd(balances, previous_usd_nok, previous_brl_nok)
        after = _value_usd(balances, current_usd_nok, current_brl_nok)
        fx_effect += after - before
        previous_usd_nok = current_usd_nok
        previous_brl_nok = current_brl_nok

        for item in items:
            currency = str(item.get("currency") or "").upper()
            amount = _movement_original(item)
            if currency not in SUPPORTED_CURRENCIES or amount is None:
                skipped_movements += 1
                continue
            balances[currency] += amount
            applied_movements += 1

    final_usd_nok, final_brl_nok, final_usd_date, final_brl_date = end_rates
    before_final = _value_usd(balances, previous_usd_nok, previous_brl_nok)
    after_final = _value_usd(balances, final_usd_nok, final_brl_nok)
    fx_effect += after_final - before_final

    actual_cash_fx = Decimal(str(outcome["cash_fx_effect_usd"]))
    pnl_fx = Decimal(str(outcome["pnl_fx_result_usd"]))
    error = fx_effect - actual_cash_fx
    abs_error = abs(error)
    denominator = abs(actual_cash_fx) if actual_cash_fx != 0 else Decimal("1")
    accuracy = max(Decimal("0"), Decimal("100") * (Decimal("1") - abs_error / denominator))
    sign_correct = (fx_effect >= 0) == (actual_cash_fx >= 0)
    model_end_cash = _value_usd(balances, final_usd_nok, final_brl_nok)
    actual_end_cash = Decimal(str(end_anchor["total_cash_usd"]))
    end_cash_gap = model_end_cash - actual_end_cash

    return {
        "ready": True,
        "period_start": start,
        "period_end": end,
        "model_cash_fx_usd_m": _float(fx_effect / Decimal("1000000")),
        "actual_cash_fx_usd_m": _float(actual_cash_fx / Decimal("1000000")),
        "reported_pnl_fx_usd_m": _float(pnl_fx / Decimal("1000000")),
        "error_usd_m": _float(error / Decimal("1000000")),
        "absolute_error_usd_m": _float(abs_error / Decimal("1000000")),
        "accuracy_pct": _float(accuracy),
        "sign_correct": sign_correct,
        "applied_known_movements": applied_movements,
        "skipped_movements": skipped_movements,
        "model_end_cash_usd_m": _float(model_end_cash / Decimal("1000000")),
        "actual_end_cash_usd_m": _float(actual_end_cash / Decimal("1000000")),
        "unmodelled_end_cash_gap_usd_m": _float(end_cash_gap / Decimal("1000000")),
        "start_fx_dates": {"USD_NOK": usd_rate_date, "BRL_NOK": brl_rate_date},
        "end_fx_dates": {"USD_NOK": final_usd_date, "BRL_NOK": final_brl_date},
        "source_document_id": outcome.get("source_document_id"),
        "method": "start-anchor-known-flows-daily-fx-v1",
    }


def fx_backtest_summary(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        anchors = _anchors(connection)
        outcomes = _outcomes(connection)
        if not outcomes:
            return {"ready": False, "reason": "missing_reported_fx_outcomes"}
        periods = [_period_backtest(connection, outcome, anchors) for outcome in outcomes]

    ready_periods = [item for item in periods if item.get("ready")]
    if not ready_periods:
        return {"ready": False, "reason": "no_backtest_period_ready", "periods": periods}

    mae = sum(Decimal(str(item["absolute_error_usd_m"])) for item in ready_periods) / Decimal(len(ready_periods))
    sign_hits = sum(1 for item in ready_periods if item.get("sign_correct"))
    return {
        "ready": True,
        "periods": periods,
        "summary": {
            "periods_ready": len(ready_periods),
            "periods_total": len(periods),
            "mean_absolute_error_usd_m": _float(mae),
            "sign_hit_rate_pct": 100.0 * sign_hits / len(ready_periods),
            "primary_target": "cash-flow FX effect on cash and cash equivalents",
            "pnl_fx_role": "diagnostic_only",
        },
        "method_note": (
            "Backtesten starter med kildebasert kontantfordeling. Rapportert USD/BRL brukes direkte, "
            "eksplisitt NOK eller eldre ufordelt residual holdes i NOK, og kjente kontantstrømmer legges "
            "til i opprinnelig valuta. Valutaeffekten isoleres mellom strømdatoene med historiske "
            "ECB-krysskurser. Resultatført netto valutaresultat brukes ikke som fasit fordi det også "
            "påvirkes av andre monetære poster enn kontanter."
        ),
    }

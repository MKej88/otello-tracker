from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.db.repository import decimal_text

DATA_PATH = Path(__file__).resolve().parents[1] / "history" / "data" / "otello_option_program_2025.json"
MAX_LOOKBACK_DAYS = 7
DAYS_PER_YEAR = Decimal("365.25")


def load_option_program() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black_scholes_call(
    spot: Decimal,
    strike: Decimal,
    years: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
    dividend_yield: Decimal = Decimal("0"),
) -> Decimal:
    if spot <= 0:
        return Decimal("0")
    if strike <= 0:
        return spot
    if years <= 0 or volatility <= 0:
        intrinsic = spot - strike
        return intrinsic if intrinsic > 0 else Decimal("0")

    s = float(spot)
    k = float(strike)
    t = float(years)
    r = float(risk_free_rate)
    sigma = float(volatility)
    q = float(dividend_yield)
    root_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    value = s * math.exp(-q * t) * _normal_cdf(d1) - k * math.exp(-r * t) * _normal_cdf(d2)
    return Decimal(str(max(value, 0.0)))


def _preferred_otec_price(connection, as_of_date: str):
    floor_date = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT mp.id, mp.trading_date, mp.observed_at, mp.price_type,
               mp.price, mp.quality, s.code AS source_code
        FROM market_prices mp
        JOIN instruments i ON i.id = mp.instrument_id
        JOIN sources s ON s.id = mp.source_id
        WHERE i.symbol = 'OTEC' AND mp.price_type IN ('CLOSE', 'LAST')
          AND mp.trading_date <= ? AND mp.trading_date >= ?
        ORDER BY mp.trading_date DESC,
                 CASE s.code WHEN 'EURONEXT' THEN 0 WHEN 'INVESTING' THEN 2 ELSE 5 END,
                 CASE mp.price_type WHEN 'CLOSE' THEN 0 WHEN 'LAST' THEN 1 ELSE 5 END,
                 CASE mp.quality WHEN 'DIRECT' THEN 0 ELSE 1 END,
                 mp.observed_at DESC,
                 mp.id DESC
        LIMIT 1
        """,
        (as_of_date, floor_date),
    ).fetchone()


def _nearest_usd_nok(connection, as_of_date: str):
    floor_date = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT id, substr(observed_at, 1, 10) AS rate_date, rate
        FROM fx_rates
        WHERE base_currency = 'USD' AND quote_currency = 'NOK'
          AND substr(observed_at, 1, 10) <= ?
          AND substr(observed_at, 1, 10) >= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1
        """,
        (as_of_date, floor_date),
    ).fetchone()


def _interpolate(start: Decimal, end: Decimal, fraction: Decimal) -> Decimal:
    return start + (end - start) * fraction


def _parameter_pair(manifest: dict[str, Any], current: date) -> tuple[Decimal, Decimal]:
    anchors = manifest["valuation_anchors"]
    first = anchors[0]
    last = anchors[-1]
    first_day = date.fromisoformat(first["as_of_date"])
    last_day = date.fromisoformat(last["as_of_date"])

    if current <= first_day:
        return Decimal(first["risk_free_rate"]), Decimal(first["volatility"])
    if current >= last_day:
        return Decimal(last["risk_free_rate"]), Decimal(last["volatility"])

    fraction = Decimal((current - first_day).days) / Decimal((last_day - first_day).days)
    return (
        _interpolate(Decimal(first["risk_free_rate"]), Decimal(last["risk_free_rate"]), fraction),
        _interpolate(Decimal(first["volatility"]), Decimal(last["volatility"]), fraction),
    )


def _adjusted_strike(connection, manifest: dict[str, Any], as_of_date: str) -> tuple[Decimal, list[dict[str, Any]]]:
    program = manifest["program"]
    grant_date = program["grant_date"]
    base_strike = Decimal(program["strike_price_nok"])
    rows = connection.execute(
        """
        SELECT ca.id, ca.action_type, ca.payment_date, ca.amount_per_share
        FROM corporate_actions ca
        JOIN instruments i ON i.id = ca.issuer_instrument_id
        WHERE i.symbol = 'OTEC'
          AND ca.action_type IN ('DISTRIBUTION', 'DIVIDEND')
          AND ca.payment_date IS NOT NULL
          AND ca.amount_per_share IS NOT NULL
          AND ca.currency = 'NOK'
          AND ca.payment_date > ? AND ca.payment_date <= ?
        ORDER BY ca.payment_date, ca.id
        """,
        (grant_date, as_of_date),
    ).fetchall()
    adjustments: list[dict[str, Any]] = []
    total = Decimal("0")
    for row in rows:
        amount = Decimal(row["amount_per_share"])
        total += amount
        adjustments.append(
            {
                "corporate_action_id": row["id"],
                "action_type": row["action_type"],
                "payment_date": row["payment_date"],
                "amount_per_share_nok": decimal_text(amount),
            }
        )
    strike = base_strike - total
    return (strike if strike > 0 else Decimal("0")), adjustments


def _years_to_expected_settlement(manifest: dict[str, Any], current: date) -> Decimal:
    settlement = date.fromisoformat(manifest["program"]["expected_settlement_date"])
    remaining = Decimal((settlement - current).days) / DAYS_PER_YEAR
    return remaining if remaining > 0 else Decimal("0")


def _anchor_recognition_fraction(connection, manifest: dict[str, Any]) -> Decimal | None:
    anchor = manifest["valuation_anchors"][-1]
    reported_usd_raw = anchor.get("reported_liability_usd")
    if reported_usd_raw is None:
        return None
    fx = _nearest_usd_nok(connection, anchor["as_of_date"])
    if fx is None:
        return None
    current = date.fromisoformat(anchor["as_of_date"])
    risk_free, volatility = _parameter_pair(manifest, current)
    strike, _ = _adjusted_strike(connection, manifest, anchor["as_of_date"])
    fair_value = black_scholes_call(
        Decimal(anchor["spot_price_nok"]),
        strike,
        _years_to_expected_settlement(manifest, current),
        risk_free,
        volatility,
    )
    gross = fair_value * Decimal(manifest["program"]["option_count"])
    if gross <= 0:
        return None
    reported_nok = Decimal(reported_usd_raw) * Decimal(fx["rate"])
    return reported_nok / gross


def _recognition_fraction(connection, manifest: dict[str, Any], current: date) -> Decimal | None:
    grant = date.fromisoformat(manifest["program"]["grant_date"])
    report_anchor = date.fromisoformat(manifest["valuation_anchors"][-1]["as_of_date"])
    settlement = date.fromisoformat(manifest["program"]["expected_settlement_date"])
    anchor_fraction = _anchor_recognition_fraction(connection, manifest)
    if anchor_fraction is None:
        return None
    if current <= grant:
        return Decimal("0")
    if current == report_anchor:
        return anchor_fraction
    if current < report_anchor:
        elapsed = Decimal((current - grant).days)
        span = Decimal((report_anchor - grant).days)
        return anchor_fraction * elapsed / span
    if current >= settlement:
        return Decimal("1")
    elapsed = Decimal((current - report_anchor).days)
    span = Decimal((settlement - report_anchor).days)
    return anchor_fraction + (Decimal("1") - anchor_fraction) * elapsed / span


def option_liability_for_day(connection, as_of_date: str) -> dict[str, Any] | None:
    manifest = load_option_program()
    current = date.fromisoformat(as_of_date)
    grant = date.fromisoformat(manifest["program"]["grant_date"])
    if current < grant:
        return {
            "liability_nok": Decimal("0"),
            "liability_usd": Decimal("0"),
            "fair_value_per_option_nok": None,
            "recognition_fraction": Decimal("0"),
            "spot_nok": None,
            "strike_nok": Decimal(manifest["program"]["strike_price_nok"]),
            "quality": "NONE",
            "inputs": {"program_version": manifest["version"], "before_grant": True},
        }

    price = _preferred_otec_price(connection, as_of_date)
    usd_nok = _nearest_usd_nok(connection, as_of_date)
    recognition = _recognition_fraction(connection, manifest, current)
    if price is None or usd_nok is None or recognition is None:
        return None

    strike, strike_adjustments = _adjusted_strike(connection, manifest, as_of_date)
    risk_free, volatility = _parameter_pair(manifest, current)
    years = _years_to_expected_settlement(manifest, current)
    spot = Decimal(price["price"])
    fair_value = black_scholes_call(spot, strike, years, risk_free, volatility)
    gross_fair_value = fair_value * Decimal(manifest["program"]["option_count"])
    liability_nok = gross_fair_value * recognition

    report_anchor = manifest["valuation_anchors"][-1]
    if as_of_date == report_anchor["as_of_date"] and report_anchor.get("reported_liability_usd") is not None:
        liability_nok = Decimal(report_anchor["reported_liability_usd"]) * Decimal(usd_nok["rate"])
        quality = "REPORTED_CALIBRATED"
    elif current < date.fromisoformat(report_anchor["as_of_date"]):
        quality = "INTERPOLATED_TO_REPORTED"
    else:
        quality = "FORECAST_MARK_TO_MARKET"

    liability_usd = liability_nok / Decimal(usd_nok["rate"])
    inputs = {
        "program_version": manifest["version"],
        "date": as_of_date,
        "option_count": manifest["program"]["option_count"],
        "spot_price_id": price["id"],
        "spot_price_date": price["trading_date"],
        "spot_price_type": price["price_type"],
        "spot_nok": decimal_text(spot),
        "strike_nok": decimal_text(strike),
        "strike_adjustments": strike_adjustments,
        "expected_settlement_date": manifest["program"]["expected_settlement_date"],
        "time_to_maturity_years": decimal_text(years),
        "risk_free_rate": decimal_text(risk_free),
        "volatility": decimal_text(volatility),
        "dividend_yield": "0",
        "fair_value_per_option_nok": decimal_text(fair_value),
        "gross_fair_value_nok": decimal_text(gross_fair_value),
        "recognition_fraction": decimal_text(recognition),
        "usd_nok_rate_id": usd_nok["id"],
        "usd_nok_rate_date": usd_nok["rate_date"],
        "usd_nok": usd_nok["rate"],
        "quality": quality,
    }
    inputs["inputs_hash"] = _hash(inputs)
    return {
        "liability_nok": liability_nok,
        "liability_usd": liability_usd,
        "fair_value_per_option_nok": fair_value,
        "recognition_fraction": recognition,
        "spot_nok": spot,
        "strike_nok": strike,
        "quality": quality,
        "inputs": inputs,
    }

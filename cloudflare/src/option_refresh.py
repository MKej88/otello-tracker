from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any

from cash_refresh import decimal_text, nearest_fx, stable_hash
from repository import D1WriteRepository

DAYS_PER_YEAR = Decimal("365.25")
OPTION_MANIFEST = {
    "version": "2026-08-17.1",
    "program": {
        "grant_date": "2025-09-15",
        "option_count": 4_100_000,
        "strike_price_nok": "12.5637",
        "expected_settlement_date": "2028-09-15",
    },
    "valuation_anchors": [
        {
            "as_of_date": "2025-09-15",
            "spot_price_nok": "13.10",
            "risk_free_rate": "0.037",
            "volatility": "0.222",
            "reported_liability_usd": None,
        },
        {
            "as_of_date": "2025-12-31",
            "spot_price_nok": "18.15",
            "risk_free_rate": "0.039",
            "volatility": "0.234",
            "reported_liability_usd": "314000",
        },
    ],
}


def _to_date(value: str) -> date:
    return date.fromisoformat(value)


async def preferred_price(
    repository: D1WriteRepository,
    symbol: str,
    as_of_date: str,
) -> dict[str, Any] | None:
    floor = (_to_date(as_of_date).toordinal() - 7)
    floor_date = date.fromordinal(floor).isoformat()
    return await repository.first(
        """
        SELECT mp.id,mp.trading_date,mp.observed_at,mp.price_type,mp.price,mp.quality,
               s.code AS source_code
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol=? AND mp.price_type IN ('CLOSE','LAST')
          AND mp.trading_date<=? AND mp.trading_date>=?
        ORDER BY mp.trading_date DESC,
                 CASE s.code WHEN 'EURONEXT' THEN 0 WHEN 'B3' THEN 0
                             WHEN 'INVESTING' THEN 2 ELSE 5 END,
                 CASE mp.price_type WHEN 'CLOSE' THEN 0 WHEN 'LAST' THEN 1 ELSE 5 END,
                 CASE mp.quality WHEN 'DIRECT' THEN 0 ELSE 1 END,
                 mp.observed_at DESC,mp.id DESC
        LIMIT 1
        """,
        (symbol, as_of_date, floor_date),
    )


async def _adjusted_strike(
    repository: D1WriteRepository,
    as_of_date: str,
) -> tuple[Decimal, list[dict[str, Any]]]:
    program = OPTION_MANIFEST["program"]
    rows = await repository.all(
        """
        SELECT ca.id,ca.action_type,ca.payment_date,ca.amount_per_share
        FROM corporate_actions ca
        JOIN instruments i ON i.id=ca.issuer_instrument_id
        WHERE i.symbol='OTEC'
          AND ca.action_type IN ('DISTRIBUTION','DIVIDEND')
          AND ca.payment_date IS NOT NULL
          AND ca.amount_per_share IS NOT NULL
          AND ca.currency='NOK'
          AND ca.payment_date>?
          AND ca.payment_date<=?
        ORDER BY ca.payment_date,ca.id
        """,
        (program["grant_date"], as_of_date),
    )
    total = Decimal("0")
    adjustments: list[dict[str, Any]] = []
    for row in rows:
        amount = Decimal(str(row["amount_per_share"]))
        total += amount
        adjustments.append(
            {
                "corporate_action_id": int(row["id"]),
                "action_type": row["action_type"],
                "payment_date": row["payment_date"],
                "amount_per_share_nok": decimal_text(amount),
            }
        )
    strike = Decimal(str(program["strike_price_nok"])) - total
    return max(strike, Decimal("0")), adjustments


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _black_scholes_call(
    spot: Decimal,
    strike: Decimal,
    years: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
) -> Decimal:
    if spot <= 0:
        return Decimal("0")
    if strike <= 0:
        return spot
    if years <= 0 or volatility <= 0:
        return max(spot - strike, Decimal("0"))
    s = float(spot)
    k = float(strike)
    t = float(years)
    r = float(risk_free_rate)
    sigma = float(volatility)
    root_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    value = s * _normal_cdf(d1) - k * math.exp(-r * t) * _normal_cdf(d2)
    return Decimal(str(max(value, 0.0)))


def _parameters(current: date) -> tuple[Decimal, Decimal]:
    first, last = OPTION_MANIFEST["valuation_anchors"]
    first_day = _to_date(first["as_of_date"])
    last_day = _to_date(last["as_of_date"])
    if current <= first_day:
        return Decimal(first["risk_free_rate"]), Decimal(first["volatility"])
    if current >= last_day:
        return Decimal(last["risk_free_rate"]), Decimal(last["volatility"])
    fraction = Decimal((current - first_day).days) / Decimal((last_day - first_day).days)
    return (
        Decimal(first["risk_free_rate"])
        + (Decimal(last["risk_free_rate"]) - Decimal(first["risk_free_rate"])) * fraction,
        Decimal(first["volatility"])
        + (Decimal(last["volatility"]) - Decimal(first["volatility"])) * fraction,
    )


def _years_to_settlement(current: date) -> Decimal:
    settlement = _to_date(OPTION_MANIFEST["program"]["expected_settlement_date"])
    return max(Decimal((settlement - current).days) / DAYS_PER_YEAR, Decimal("0"))


async def _reported_recognition_fraction(repository: D1WriteRepository) -> Decimal | None:
    anchor = OPTION_MANIFEST["valuation_anchors"][-1]
    usd = await nearest_fx(repository, "USD", anchor["as_of_date"])
    if usd is None:
        return None
    current = _to_date(anchor["as_of_date"])
    risk_free, volatility = _parameters(current)
    strike, _ = await _adjusted_strike(repository, anchor["as_of_date"])
    fair_value = _black_scholes_call(
        Decimal(anchor["spot_price_nok"]),
        strike,
        _years_to_settlement(current),
        risk_free,
        volatility,
    )
    gross = fair_value * Decimal(str(OPTION_MANIFEST["program"]["option_count"]))
    if gross <= 0:
        return None
    reported_nok = Decimal(anchor["reported_liability_usd"]) * Decimal(str(usd["rate"]))
    return reported_nok / gross


async def option_liability_for_day(
    repository: D1WriteRepository,
    as_of_date: str,
) -> dict[str, Any] | None:
    current = _to_date(as_of_date)
    grant = _to_date(OPTION_MANIFEST["program"]["grant_date"])
    if current < grant:
        return {
            "liability_nok": Decimal("0"),
            "liability_usd": Decimal("0"),
            "fair_value_per_option_nok": None,
            "recognition_fraction": Decimal("0"),
            "spot_nok": None,
            "strike_nok": Decimal(OPTION_MANIFEST["program"]["strike_price_nok"]),
            "quality": "NONE",
            "inputs": {
                "program_version": OPTION_MANIFEST["version"],
                "before_grant": True,
            },
        }

    price = await preferred_price(repository, "OTEC", as_of_date)
    usd = await nearest_fx(repository, "USD", as_of_date)
    anchor_recognition = await _reported_recognition_fraction(repository)
    if price is None or usd is None or anchor_recognition is None:
        return None

    reported_day = _to_date(OPTION_MANIFEST["valuation_anchors"][-1]["as_of_date"])
    if current <= grant:
        recognition = Decimal("0")
    elif current >= reported_day:
        recognition = anchor_recognition
    else:
        recognition = (
            anchor_recognition
            * Decimal((current - grant).days)
            / Decimal((reported_day - grant).days)
        )

    strike, adjustments = await _adjusted_strike(repository, as_of_date)
    risk_free, volatility = _parameters(current)
    years = _years_to_settlement(current)
    spot = Decimal(str(price["price"]))
    fair_value = _black_scholes_call(spot, strike, years, risk_free, volatility)
    gross = fair_value * Decimal(str(OPTION_MANIFEST["program"]["option_count"]))
    liability_nok = gross * recognition

    reported_anchor = OPTION_MANIFEST["valuation_anchors"][-1]
    if as_of_date == reported_anchor["as_of_date"]:
        liability_nok = (
            Decimal(reported_anchor["reported_liability_usd"])
            * Decimal(str(usd["rate"]))
        )
        quality = "REPORTED_CALIBRATED"
    elif current < reported_day:
        quality = "INTERPOLATED_TO_REPORTED"
    else:
        quality = "FORECAST_MARK_TO_MARKET"

    liability_usd = liability_nok / Decimal(str(usd["rate"]))
    inputs = {
        "program_version": OPTION_MANIFEST["version"],
        "date": as_of_date,
        "option_count": OPTION_MANIFEST["program"]["option_count"],
        "spot_price_id": int(price["id"]),
        "spot_price_date": price["trading_date"],
        "spot_price_type": price["price_type"],
        "spot_nok": decimal_text(spot),
        "strike_nok": decimal_text(strike),
        "strike_adjustments": adjustments,
        "expected_settlement_date": OPTION_MANIFEST["program"]["expected_settlement_date"],
        "time_to_maturity_years": decimal_text(years),
        "risk_free_rate": decimal_text(risk_free),
        "volatility": decimal_text(volatility),
        "dividend_yield": "0",
        "fair_value_per_option_nok": decimal_text(fair_value),
        "gross_fair_value_nok": decimal_text(gross),
        "recognition_fraction": decimal_text(recognition),
        "recognition_policy": (
            "HOLD_LAST_REPORTED_FACTOR_UNTIL_NEW_REPORT_OR_QUALIFYING_BEMOBI_DISPOSAL"
        ),
        "usd_nok_rate_id": int(usd["id"]),
        "usd_nok_rate_date": usd["rate_date"],
        "usd_nok": usd["rate"],
        "quality": quality,
    }
    inputs["inputs_hash"] = stable_hash(inputs)
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

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

MAX_LOOKBACK_DAYS = 7
DAYS_PER_YEAR = Decimal("365.25")

# Mirrors backend/app/history/data/otello_option_program_2025.json version 2026-08-17.1.
# Keep this bounded reference input embedded in the Worker so the 30-minute fast path
# does not depend on filesystem access in the Python Worker runtime. New validated
# financial reports can extend the reported liability anchors through D1 source docs.
OPTION_PROGRAM: dict[str, Any] = {
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
            "source": "STATIC_PROGRAM",
        },
        {
            "as_of_date": "2025-12-31",
            "spot_price_nok": "18.15",
            "risk_free_rate": "0.039",
            "volatility": "0.234",
            "reported_liability_usd": "314000",
            "source": "AUDITED_ANNUAL_REPORT_2025",
        },
    ],
}


def decimal_text(value: Decimal | str | int | float) -> str:
    return format(Decimal(str(value)), "f")


def _hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


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


async def _preferred_otec_price(repository, as_of_date: str) -> dict[str, Any] | None:
    floor_date = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
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
    )


async def _nearest_usd_nok(repository, as_of_date: str) -> dict[str, Any] | None:
    floor_date = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT id, substr(observed_at, 1, 10) AS rate_date, rate
        FROM fx_rates
        WHERE base_currency = 'USD' AND quote_currency = 'NOK'
          AND substr(observed_at, 1, 10) <= ?
          AND substr(observed_at, 1, 10) >= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1
        """,
        (as_of_date, floor_date),
    )


async def _valuation_anchors(repository) -> list[dict[str, Any]]:
    anchors = [dict(item) for item in OPTION_PROGRAM["valuation_anchors"]]
    last_static = anchors[-1]
    rows = await repository.all(
        """
        SELECT id, published_at, metadata_json
        FROM source_documents
        WHERE document_type='OTELLO_FINANCIAL_REPORT'
        ORDER BY published_at, id
        """
    )
    dynamic: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = _metadata(row.get("metadata_json"))
        if metadata.get("auto_apply_status") != "APPLIED":
            continue
        validation = metadata.get("validation") or {}
        facts = metadata.get("facts") or {}
        if validation.get("valid") is not True or not isinstance(facts, dict):
            continue
        report_date = str(facts.get("report_date") or "")[:10]
        liability = facts.get("option_liability_usd")
        if not report_date or liability in {None, ""}:
            continue
        try:
            if Decimal(str(liability)) < 0:
                continue
        except Exception:
            continue
        dynamic[report_date] = {
            "as_of_date": report_date,
            "spot_price_nok": facts.get("option_spot_nok"),
            "risk_free_rate": facts.get("option_risk_free_rate") or last_static["risk_free_rate"],
            "volatility": facts.get("option_volatility") or last_static["volatility"],
            "reported_liability_usd": str(liability),
            "source": "AUTO_FINANCIAL_REPORT",
            "source_document_id": int(row["id"]),
            "parameter_quality": (
                "REPORT_INPUTS"
                if facts.get("option_risk_free_rate") is not None
                and facts.get("option_volatility") is not None
                else "PRIOR_REPORTED_VALUATION_INPUTS"
            ),
        }
    by_date = {str(item["as_of_date"]): item for item in anchors}
    by_date.update(dynamic)
    return [by_date[key] for key in sorted(by_date)]


def _interpolate(start: Decimal, end: Decimal, fraction: Decimal) -> Decimal:
    return start + (end - start) * fraction


async def _parameter_pair(repository, current: date) -> tuple[Decimal, Decimal, dict[str, Any]]:
    anchors = await _valuation_anchors(repository)
    first = anchors[0]
    eligible = [item for item in anchors if date.fromisoformat(str(item["as_of_date"])) <= current]
    active = eligible[-1] if eligible else first

    static_first = OPTION_PROGRAM["valuation_anchors"][0]
    static_last = OPTION_PROGRAM["valuation_anchors"][-1]
    first_day = date.fromisoformat(static_first["as_of_date"])
    last_day = date.fromisoformat(static_last["as_of_date"])
    if first_day < current < last_day:
        fraction = Decimal((current - first_day).days) / Decimal((last_day - first_day).days)
        return (
            _interpolate(
                Decimal(static_first["risk_free_rate"]),
                Decimal(static_last["risk_free_rate"]),
                fraction,
            ),
            _interpolate(
                Decimal(static_first["volatility"]),
                Decimal(static_last["volatility"]),
                fraction,
            ),
            {"as_of_date": current.isoformat(), "source": "INTERPOLATED_STATIC_PARAMETERS"},
        )
    return Decimal(str(active["risk_free_rate"])), Decimal(str(active["volatility"])), active


async def _adjusted_strike(
    repository,
    as_of_date: str,
) -> tuple[Decimal, list[dict[str, Any]]]:
    program = OPTION_PROGRAM["program"]
    base_strike = Decimal(program["strike_price_nok"])
    rows = await repository.all(
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
        (program["grant_date"], as_of_date),
    )
    adjustments: list[dict[str, Any]] = []
    total = Decimal("0")
    for row in rows:
        amount = Decimal(str(row["amount_per_share"]))
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


def _years_to_expected_settlement(current: date) -> Decimal:
    settlement = date.fromisoformat(OPTION_PROGRAM["program"]["expected_settlement_date"])
    remaining = Decimal((settlement - current).days) / DAYS_PER_YEAR
    return remaining if remaining > 0 else Decimal("0")


async def _anchor_recognition_fraction(repository, anchor: dict[str, Any]) -> Decimal | None:
    reported_usd_raw = anchor.get("reported_liability_usd")
    if reported_usd_raw is None:
        return None
    anchor_date = str(anchor["as_of_date"])
    fx = await _nearest_usd_nok(repository, anchor_date)
    if fx is None:
        return None
    current = date.fromisoformat(anchor_date)
    risk_free = Decimal(str(anchor["risk_free_rate"]))
    volatility = Decimal(str(anchor["volatility"]))
    strike, _ = await _adjusted_strike(repository, anchor_date)
    spot_raw = anchor.get("spot_price_nok")
    if spot_raw is None:
        price = await _preferred_otec_price(repository, anchor_date)
        if price is None:
            return None
        spot = Decimal(str(price["price"]))
    else:
        spot = Decimal(str(spot_raw))
    fair_value = black_scholes_call(
        spot,
        strike,
        _years_to_expected_settlement(current),
        risk_free,
        volatility,
    )
    gross = fair_value * Decimal(OPTION_PROGRAM["program"]["option_count"])
    if gross <= 0:
        return Decimal("0") if Decimal(str(reported_usd_raw)) == 0 else None
    reported_nok = Decimal(str(reported_usd_raw)) * Decimal(str(fx["rate"]))
    return reported_nok / gross


async def _reported_anchors(repository) -> list[dict[str, Any]]:
    return [
        item
        for item in await _valuation_anchors(repository)
        if item.get("reported_liability_usd") is not None
    ]


async def _recognition_fraction(
    repository,
    current: date,
) -> tuple[Decimal | None, dict[str, Any] | None]:
    grant = date.fromisoformat(OPTION_PROGRAM["program"]["grant_date"])
    anchors = await _reported_anchors(repository)
    if not anchors:
        return None, None

    eligible = [item for item in anchors if date.fromisoformat(str(item["as_of_date"])) <= current]
    if eligible:
        active = eligible[-1]
        return await _anchor_recognition_fraction(repository, active), active

    first = anchors[0]
    first_day = date.fromisoformat(str(first["as_of_date"]))
    fraction = await _anchor_recognition_fraction(repository, first)
    if fraction is None:
        return None, first
    if current <= grant:
        return Decimal("0"), first
    elapsed = Decimal((current - grant).days)
    span = Decimal((first_day - grant).days)
    if span <= 0:
        return fraction, first
    return fraction * elapsed / span, first


async def option_liability_for_day(repository, as_of_date: str) -> dict[str, Any] | None:
    current = date.fromisoformat(as_of_date)
    grant = date.fromisoformat(OPTION_PROGRAM["program"]["grant_date"])
    if current < grant:
        return {
            "liability_nok": Decimal("0"),
            "liability_usd": Decimal("0"),
            "fair_value_per_option_nok": None,
            "recognition_fraction": Decimal("0"),
            "spot_nok": None,
            "strike_nok": Decimal(OPTION_PROGRAM["program"]["strike_price_nok"]),
            "quality": "NONE",
            "inputs": {"program_version": OPTION_PROGRAM["version"], "before_grant": True},
        }

    price = await _preferred_otec_price(repository, as_of_date)
    usd_nok = await _nearest_usd_nok(repository, as_of_date)
    recognition, report_anchor = await _recognition_fraction(repository, current)
    if price is None or usd_nok is None or recognition is None or report_anchor is None:
        return None

    strike, strike_adjustments = await _adjusted_strike(repository, as_of_date)
    risk_free, volatility, parameter_anchor = await _parameter_pair(repository, current)
    years = _years_to_expected_settlement(current)
    spot = Decimal(str(price["price"]))
    fair_value = black_scholes_call(spot, strike, years, risk_free, volatility)
    gross_fair_value = fair_value * Decimal(OPTION_PROGRAM["program"]["option_count"])
    liability_nok = gross_fair_value * recognition

    report_anchor_date = str(report_anchor["as_of_date"])
    if as_of_date == report_anchor_date and report_anchor.get("reported_liability_usd") is not None:
        liability_nok = Decimal(str(report_anchor["reported_liability_usd"])) * Decimal(
            str(usd_nok["rate"])
        )
        quality = "REPORTED_CALIBRATED"
    elif current < date.fromisoformat(report_anchor_date):
        quality = "INTERPOLATED_TO_REPORTED"
    else:
        quality = "FORECAST_MARK_TO_MARKET"

    usd_rate = Decimal(str(usd_nok["rate"]))
    liability_usd = liability_nok / usd_rate
    inputs = {
        "program_version": OPTION_PROGRAM["version"],
        "date": as_of_date,
        "option_count": OPTION_PROGRAM["program"]["option_count"],
        "spot_price_id": price["id"],
        "spot_price_date": price["trading_date"],
        "spot_price_type": price["price_type"],
        "spot_nok": decimal_text(spot),
        "strike_nok": decimal_text(strike),
        "strike_adjustments": strike_adjustments,
        "expected_settlement_date": OPTION_PROGRAM["program"]["expected_settlement_date"],
        "time_to_maturity_years": decimal_text(years),
        "risk_free_rate": decimal_text(risk_free),
        "volatility": decimal_text(volatility),
        "dividend_yield": "0",
        "fair_value_per_option_nok": decimal_text(fair_value),
        "gross_fair_value_nok": decimal_text(gross_fair_value),
        "recognition_fraction": decimal_text(recognition),
        "recognition_policy": "HOLD_LAST_REPORTED_FACTOR_UNTIL_NEW_REPORT_OR_QUALIFYING_BEMOBI_DISPOSAL",
        "usd_nok_rate_id": usd_nok["id"],
        "usd_nok_rate_date": usd_nok["rate_date"],
        "usd_nok": usd_nok["rate"],
        "quality": quality,
    }
    if report_anchor.get("source_document_id") is not None:
        inputs["reported_liability_anchor"] = {
            "as_of_date": report_anchor_date,
            "reported_liability_usd": report_anchor.get("reported_liability_usd"),
            "source": report_anchor.get("source"),
            "source_document_id": report_anchor.get("source_document_id"),
        }
    if parameter_anchor.get("source_document_id") is not None:
        inputs["parameter_anchor"] = {
            "as_of_date": parameter_anchor.get("as_of_date"),
            "source": parameter_anchor.get("source"),
            "source_document_id": parameter_anchor.get("source_document_id"),
            "quality": parameter_anchor.get("parameter_quality"),
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

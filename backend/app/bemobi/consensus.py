from __future__ import annotations

from typing import Any

from app.bemobi.consensus_history import build_consensus_history
from app.bemobi.dashboard import bemobi_dashboard
from app.bemobi.facts import latest_bemobi_fact, load_bemobi_facts, public_fact
from app.db.connection import get_connection


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _target_payload(price_brl: float | None, analysts: list[dict[str, Any]]) -> dict[str, Any]:
    targets = [
        float(item["target_price_brl"])
        for item in analysts
        if _number(item.get("target_price_brl")) is not None
    ]
    if not targets:
        return {
            "analyst_count": 0,
            "buy_count": 0,
            "hold_count": 0,
            "sell_count": 0,
            "buy_pct": 0.0,
            "average_target_brl": None,
            "high_target_brl": None,
            "low_target_brl": None,
            "upside_to_average_pct": None,
            "source": None,
            "source_url": None,
            "checked_date": None,
        }

    average = sum(targets) / len(targets)
    high = max(targets)
    low = min(targets)
    buy_count = sum(1 for item in analysts if str(item.get("rating") or "").upper() == "BUY")
    hold_count = sum(1 for item in analysts if str(item.get("rating") or "").upper() == "HOLD")
    sell_count = sum(1 for item in analysts if str(item.get("rating") or "").upper() == "SELL")
    upside = None if price_brl is None or price_brl <= 0 else (average / price_brl - 1) * 100
    checked_dates = [str(item.get("_as_of_date")) for item in analysts if item.get("_as_of_date")]
    return {
        "analyst_count": len(analysts),
        "buy_count": buy_count,
        "hold_count": hold_count,
        "sell_count": sell_count,
        "buy_pct": buy_count / len(analysts) * 100,
        "average_target_brl": average,
        "high_target_brl": high,
        "low_target_brl": low,
        "upside_to_average_pct": upside,
        "source": analysts[0].get("_source_name"),
        "source_url": analysts[0].get("_source_url"),
        "checked_date": max(checked_dates) if checked_dates else None,
    }


def _forward_payload(
    price_brl: float | None,
    total_shares: int | None,
    forward_consensus: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    market_cap = None
    if price_brl is not None and price_brl > 0 and total_shares is not None and total_shares > 0:
        market_cap = price_brl * total_shares / 1_000_000

    payload: list[dict[str, Any]] = []
    for fact in forward_consensus:
        item = public_fact(fact) or {}
        net_debt = float(item["net_debt_mbrl"])
        ebitda = float(item["ebitda_mbrl"])
        ebit = float(item["ebit_mbrl"])
        net_income = float(item["net_income_mbrl"])
        enterprise_value = None if market_cap is None else market_cap + net_debt
        row = dict(item)
        row.update(
            {
                "market_cap_mbrl": market_cap,
                "enterprise_value_mbrl": enterprise_value,
                "pe": None if market_cap is None or net_income <= 0 else market_cap / net_income,
                "earnings_yield_pct": None if market_cap is None or market_cap <= 0 else net_income / market_cap * 100,
                "ev_ebitda": None if enterprise_value is None or ebitda <= 0 else enterprise_value / ebitda,
                "ev_ebit": None if enterprise_value is None or ebit <= 0 else enterprise_value / ebit,
            }
        )
        payload.append(row)
    payload.sort(key=lambda item: int(item.get("year") or 0))
    return payload


def _forward_year_range(years: list[dict[str, Any]]) -> str | None:
    values = [int(item["year"]) for item in years if item.get("year") is not None]
    if not values:
        return None
    first, last = min(values), max(values)
    return f"{first}E" if first == last else f"{first}E–{last}E"


def _beat_miss_payload(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fact in facts:
        item = public_fact(fact) or {}
        metrics = []
        for metric in item.get("metrics") or []:
            estimate = float(metric["estimate"])
            actual = float(metric["actual"])
            metrics.append(
                {
                    **metric,
                    "beat_miss_pct": None if estimate == 0 else (actual / estimate - 1) * 100,
                }
            )
        rows.append(
            {
                **item,
                "source_url": item.get("source_url") or fact.get("_source_url"),
                "metrics": metrics,
            }
        )
    return rows


def bemobi_consensus(database_path: str | None = None) -> dict[str, Any]:
    bemobi = bemobi_dashboard(database_path)
    if not bemobi.get("ready"):
        return {
            "ready": False,
            "reason": "bemobi_dashboard_not_ready",
        }

    with get_connection(database_path) as connection:
        analyst_facts = load_bemobi_facts(connection, "ANALYST")
        forward_facts = load_bemobi_facts(connection, "FORWARD_CONSENSUS")
        beat_miss_facts = load_bemobi_facts(connection, "BEAT_MISS")
        next_quarter_fact = latest_bemobi_fact(connection, "NEXT_QUARTER")
        reference_model_fact = latest_bemobi_fact(connection, "REFERENCE_MODEL")

    if not analyst_facts or not forward_facts or next_quarter_fact is None or reference_model_fact is None:
        return {
            "ready": False,
            "reason": "bemobi_consensus_facts_not_ready",
        }

    market = bemobi.get("market") or {}
    otello = bemobi.get("otello") or {}
    price_brl = _number(market.get("price_brl"))
    total_shares = int(otello.get("bemobi_total_shares") or 0) or None
    forward_years = _forward_payload(price_brl, total_shares, forward_facts)
    forward_range = _forward_year_range(forward_years)
    beat_miss = _beat_miss_payload(beat_miss_facts)
    analysts = [public_fact(item) or {} for item in analyst_facts]
    coverage = _target_payload(price_brl, analyst_facts)

    forward_source = max(
        forward_facts,
        key=lambda item: str(item.get("_as_of_date") or item.get("_published_date") or ""),
    )
    next_quarter = public_fact(next_quarter_fact) or {}
    reference_model = public_fact(reference_model_fact) or {}
    reference_model["source_url"] = reference_model.get("source_url") or reference_model_fact.get("_source_url")

    return {
        "ready": True,
        "as_of_date": market.get("price_date") or bemobi.get("as_of_date"),
        "market": {
            "price_brl": price_brl,
            "price_date": market.get("price_date"),
            "price_source": market.get("price_source"),
        },
        "coverage": coverage,
        "analysts": analysts,
        "forward_consensus": {
            "source": forward_source.get("_source_name"),
            "source_url": forward_source.get("_source_url"),
            "checked_date": forward_source.get("_as_of_date"),
            "quality": forward_source.get("_quality"),
            "analyst_count": None,
            "year_range": forward_range,
            "years": forward_years,
            "note": forward_source.get("_notes"),
        },
        "next_quarter": next_quarter,
        "beat_miss": beat_miss,
        "history_link": build_consensus_history(
            beat_miss,
            database_path,
            current_forward=forward_years,
        ),
        "reference_model": reference_model,
        "sources": [
            {
                "label": "Analytikerdekning og kursmål",
                "source": analyst_facts[0].get("_source_name"),
                "url": analyst_facts[0].get("_source_url"),
            },
            {
                "label": f"Årsestimater {forward_range or 'forward'}",
                "source": forward_source.get("_source_name"),
                "url": forward_source.get("_source_url"),
            },
            {
                "label": "XP modelloppdatering",
                "source": reference_model_fact.get("_source_name"),
                "url": reference_model_fact.get("_source_url"),
            },
        ],
    }

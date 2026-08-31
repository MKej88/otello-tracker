from __future__ import annotations

from typing import Any

from bemobi_consensus_history import build_consensus_history
from bemobi_dashboard import bemobi_dashboard
from bemobi_facts import latest_bemobi_fact, load_bemobi_facts, public_fact


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _target_payload(price_brl: float | None, analysts: list[dict[str, Any]]) -> dict[str, Any]:
    targets = [float(item["target_price_brl"]) for item in analysts if _number(item.get("target_price_brl")) is not None]
    if not targets:
        return {"analyst_count": 0, "buy_count": 0, "hold_count": 0, "sell_count": 0, "buy_pct": 0.0, "average_target_brl": None, "high_target_brl": None, "low_target_brl": None, "upside_to_average_pct": None, "source": None, "source_url": None, "checked_date": None}
    average = sum(targets) / len(targets)
    buy_count = sum(1 for item in analysts if str(item.get("rating") or "").upper() == "BUY")
    hold_count = sum(1 for item in analysts if str(item.get("rating") or "").upper() == "HOLD")
    sell_count = sum(1 for item in analysts if str(item.get("rating") or "").upper() == "SELL")
    checked_dates = [str(item.get("_as_of_date")) for item in analysts if item.get("_as_of_date")]
    return {
        "analyst_count": len(analysts),
        "buy_count": buy_count,
        "hold_count": hold_count,
        "sell_count": sell_count,
        "buy_pct": buy_count / len(analysts) * 100,
        "average_target_brl": average,
        "high_target_brl": max(targets),
        "low_target_brl": min(targets),
        "upside_to_average_pct": None if price_brl is None or price_brl <= 0 else (average / price_brl - 1) * 100,
        "source": analysts[0].get("_source_name"),
        "source_url": analysts[0].get("_source_url"),
        "checked_date": max(checked_dates) if checked_dates else None,
    }


def _broker_payload(price_brl: float | None, total_shares: int | None, broker_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    market_cap = None
    if price_brl is not None and price_brl > 0 and total_shares is not None and total_shares > 0:
        market_cap = price_brl * total_shares / 1_000_000
    payload: list[dict[str, Any]] = []
    for fact in broker_facts:
        item = public_fact(fact) or {}
        net_debt = _number(item.get("net_debt_mbrl"))
        ebitda = _number(item.get("ebitda_mbrl"))
        ebit = _number(item.get("ebit_mbrl"))
        net_income = _number(item.get("net_income_mbrl"))
        enterprise_value = None if market_cap is None or net_debt is None else market_cap + net_debt
        row = dict(item)
        row.update({
            "market_cap_mbrl": market_cap,
            "enterprise_value_mbrl": enterprise_value,
            "pe": None if market_cap is None or net_income is None or net_income <= 0 else market_cap / net_income,
            "earnings_yield_pct": None if market_cap is None or market_cap <= 0 or net_income is None else net_income / market_cap * 100,
            "ev_ebitda": None if enterprise_value is None or ebitda is None or ebitda <= 0 else enterprise_value / ebitda,
            "ev_ebit": None if enterprise_value is None or ebit is None or ebit <= 0 else enterprise_value / ebit,
        })
        payload.append(row)
    payload.sort(key=lambda item: int(item.get("year") or 0))
    return payload


def _year_range(years: list[dict[str, Any]]) -> str | None:
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
            metrics.append({**metric, "beat_miss_pct": None if estimate == 0 else (actual / estimate - 1) * 100})
        rows.append({**item, "source_url": item.get("source_url") or fact.get("_source_url"), "metrics": metrics})
    return rows


async def bemobi_consensus(repository) -> dict[str, Any]:
    bemobi = await bemobi_dashboard(repository)
    if not bemobi.get("ready"):
        return {"ready": False, "reason": "bemobi_dashboard_not_ready"}

    analyst_facts = await load_bemobi_facts(repository, "ANALYST")
    broker_facts = [
        item for item in await load_bemobi_facts(repository, "FORWARD_CONSENSUS")
        if str(item.get("_source_name") or "").lower() != "marketscreener"
    ]
    beat_miss_facts = await load_bemobi_facts(repository, "BEAT_MISS")
    next_quarter_fact = await latest_bemobi_fact(repository, "NEXT_QUARTER")
    reference_model_fact = await latest_bemobi_fact(repository, "REFERENCE_MODEL")

    if not analyst_facts or not broker_facts or next_quarter_fact is None or reference_model_fact is None:
        return {"ready": False, "reason": "bemobi_consensus_facts_not_ready"}

    market = bemobi.get("market") or {}
    otello = bemobi.get("otello") or {}
    price_brl = _number(market.get("price_brl"))
    total_shares = int(otello.get("bemobi_total_shares") or 0) or None
    broker_years = _broker_payload(price_brl, total_shares, broker_facts)
    broker_range = _year_range(broker_years)
    beat_miss = _beat_miss_payload(beat_miss_facts)
    analysts = [public_fact(item) or {} for item in analyst_facts]
    coverage = _target_payload(price_brl, analyst_facts)
    broker_source = max(broker_facts, key=lambda item: str(item.get("_published_date") or item.get("_as_of_date") or ""))
    next_quarter = public_fact(next_quarter_fact) or {}
    reference_model = public_fact(reference_model_fact) or {}
    reference_model["source_url"] = reference_model.get("source_url") or reference_model_fact.get("_source_url")

    return {
        "ready": True,
        "as_of_date": market.get("price_date") or bemobi.get("as_of_date"),
        "market": {"price_brl": price_brl, "price_date": market.get("price_date"), "price_source": market.get("price_source")},
        "coverage": coverage,
        "analysts": analysts,
        "broker_estimates": {
            "source": broker_source.get("_source_name"),
            "source_url": broker_source.get("_source_url"),
            "published_date": broker_source.get("_published_date"),
            "quality": broker_source.get("_quality"),
            "broker_count": 1,
            "year_range": broker_range,
            "years": broker_years,
            "note": broker_source.get("_notes"),
        },
        "next_quarter": next_quarter,
        "beat_miss": beat_miss,
        "history_link": await build_consensus_history(beat_miss, repository, current_forward=broker_years),
        "reference_model": reference_model,
        "sources": [
            {"label": "Analytikerdekning og kursmål", "source": analyst_facts[0].get("_source_name"), "url": analyst_facts[0].get("_source_url")},
            {"label": f"Meglerestimater {broker_range or 'forward'}", "source": broker_source.get("_source_name"), "url": broker_source.get("_source_url")},
            {"label": "XP modelloppdatering", "source": reference_model_fact.get("_source_name"), "url": reference_model_fact.get("_source_url")},
        ],
    }

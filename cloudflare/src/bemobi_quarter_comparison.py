from __future__ import annotations

import json
import math
import re
from typing import Any


def _ordinal(period: Any) -> int | None:
    match = re.fullmatch(r"([1-4])Q(\d{2})", str(period or ""))
    return None if match is None else (2000 + int(match[2])) * 4 + int(match[1]) - 1


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def build_quarter_comparison(
    result_facts: list[dict[str, Any]],
    verified_rows: list[dict[str, Any]],
    next_period: Any,
) -> dict[str, Any]:
    """Compare source-backed actuals, independent of sparse beat/miss records."""
    quarters: dict[str, dict[str, Any]] = {}
    fields = (
        ("revenue_mbrl", "adjusted_net_revenue_mbrl", "Omsetning (netto)", "value_mbrl"),
        ("adjusted_ebitda_mbrl", "adjusted_ebitda_mbrl", "Justert EBITDA", "value_mbrl"),
        ("adjusted_net_income_mbrl", "adjusted_net_income_mbrl", "Justert nettoresultat", "value_mbrl"),
        ("ebitda_margin_pct", "adjusted_ebitda_margin_pct", "Justert EBITDA-margin", "value_pct"),
    )
    # New company reports can supply the comparable core metrics without a
    # curated backfill. Never alias statutory revenue or unadjusted income.
    for fact in result_facts:
        period = str(fact.get("period") or fact.get("_fact_key") or "")
        if _ordinal(period) is None:
            continue
        metrics = []
        for metric, field, label, unit in fields:
            amount = _number(fact.get(field))
            if amount is not None:
                metrics.append({"metric": metric, "label": label, unit: amount})
        if metrics:
            quarters[period] = {
                "period": period,
                "source_name": fact.get("_source_name"),
                "source_url": fact.get("_source_url"),
                "published_date": fact.get("_published_date"),
                "source_evidence": fact.get("_quality"),
                "metrics": metrics,
            }
    for row in verified_rows:
        period = str(row.get("period") or "")
        if _ordinal(period) is None:
            continue
        try:
            items = json.loads(str(row.get("metrics_json") or "[]"))
        except (TypeError, ValueError):
            continue
        if not isinstance(items, list):
            continue
        metrics = []
        for item in items:
            if not isinstance(item, dict) or not item.get("metric"):
                continue
            amount, percent = _number(item.get("value_mbrl")), _number(item.get("value_pct"))
            if (amount is None) == (percent is None):
                continue
            unit, number = ("value_mbrl", amount) if amount is not None else ("value_pct", percent)
            metrics.append({"metric": item["metric"], "label": item.get("label"), unit: number})
        if metrics:
            quarters[period] = {
                **{key: value for key, value in row.items() if key != "metrics_json"},
                "metrics": metrics,
            }
    target = _ordinal(next_period)
    if target is None:
        return {"latest_report": None, "prior_year": None}
    earlier = [item for period, item in quarters.items() if _ordinal(period) < target]
    latest = max(earlier, key=lambda item: _ordinal(item["period"]), default=None)
    prior = next((item for period, item in quarters.items() if _ordinal(period) == target - 4), None)
    return {"latest_report": latest, "prior_year": prior}

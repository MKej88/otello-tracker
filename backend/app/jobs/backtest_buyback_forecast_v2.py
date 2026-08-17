from __future__ import annotations

import argparse
import json
import statistics
from typing import Any

from app.jobs.backtest_buyback_forecast import run_live_backtest


def _median(values: list[float], default: float = 1.0) -> float:
    return float(statistics.median(values)) if values else default


def _metrics(rows: list[dict[str, Any]], prediction_key: str) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    abs_error = 0.0
    actual_total = 0.0
    predicted_total = 0.0
    apes: list[float] = []
    within10 = 0
    within20 = 0
    zeros: list[float] = []
    for row in rows:
        predicted = float(row[prediction_key])
        actual = float(row["actual_shares"])
        error = abs(predicted - actual)
        abs_error += error
        actual_total += actual
        predicted_total += predicted
        if actual > 0:
            ape = error / actual
            apes.append(ape)
            within10 += ape <= 0.10
            within20 += ape <= 0.20
        else:
            zeros.append(predicted)
    return {
        "count": len(rows),
        "nonzero_count": len(apes),
        "zero_count": len(zeros),
        "mae_shares": round(abs_error / len(rows), 1),
        "wmape_pct": round(abs_error / actual_total * 100, 2) if actual_total else None,
        "median_ape_pct": round(statistics.median(apes) * 100, 2) if apes else None,
        "within_10_pct": round(within10 / len(apes) * 100, 1) if apes else None,
        "within_20_pct": round(within20 / len(apes) * 100, 1) if apes else None,
        "bias_pct": round((predicted_total - actual_total) / actual_total * 100, 2) if actual_total else None,
        "mean_prediction_when_actual_zero": round(statistics.mean(zeros), 1) if zeros else None,
    }


def add_program_rolling(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    output: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        same_program = [
            float(item["utilization"])
            for item in history
            if item["program_start"] == row["program_start"]
            and float(item["week_start_capacity_estimate_shares"]) > 0
        ]
        global_recent = [
            float(item["utilization"])
            for item in history[-8:]
            if float(item["week_start_capacity_estimate_shares"]) > 0
        ]
        if len(same_program) >= 2:
            factor = _median(same_program[-8:], 1.0)
            factor_source = "same_program_median"
        else:
            factor = _median(global_recent, 1.0)
            factor_source = "recent_global_fallback"
        factor = max(0.0, min(1.10, factor))

        # Price caps are handled as a confidence flag, not a deterministic zero forecast.
        # A week can move back below the cap, and Otello can amend the mandate mid-week
        # (as happened 18 Nov 2025). This preserves honest ex-ante behavior.
        row["program_rolling_factor"] = factor
        row["program_rolling_factor_source"] = factor_source
        row["program_rolling_prediction"] = min(
            float(row["remaining_before"]),
            float(row["week_start_capacity_estimate_shares"]) * factor,
        )
        output.append(row)
        history.append(row)
    return output


def _segment(rows: list[dict[str, Any]], *, start: str | None = None, program: str | None = None) -> list[dict[str, Any]]:
    result = rows
    if start is not None:
        result = [row for row in result if row["period_start"] >= start]
    if program is not None:
        result = [row for row in result if row["program_start"] == program]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default="2026-08-14")
    args = parser.parse_args()
    base = run_live_backtest(to_date=args.to)

    # Rename the old diagnostic field: 25% * ADV20 frozen at week start is a forecast
    # capacity proxy, not the exact legal ceiling for every later day in the week.
    normalized: list[dict[str, Any]] = []
    for source in base["rows"]:
        row = dict(source)
        row["week_start_capacity_estimate_shares"] = row.pop("hard_capacity_shares")
        normalized.append(row)
    rows = add_program_rolling(normalized)

    result = {
        "newsweb": base["newsweb"],
        "weeks": len(rows),
        "all_period": _metrics(rows, "program_rolling_prediction"),
        "since_2026": _metrics(_segment(rows, start="2026-01-01"), "program_rolling_prediction"),
        "feb_2026_program": _metrics(_segment(rows, program="2026-02-09"), "program_rolling_prediction"),
        "current_june_2026_program": _metrics(_segment(rows, program="2026-06-08"), "program_rolling_prediction"),
        "current_program_rows": [
            {
                "period": f"{row['period_start']}..{row['period_end']}",
                "capacity": round(row["week_start_capacity_estimate_shares"]),
                "factor": round(row["program_rolling_factor"], 4),
                "predicted": round(row["program_rolling_prediction"]),
                "actual": row["actual_shares"],
                "utilization": round(row["utilization"], 4),
            }
            for row in _segment(rows, program="2026-06-08")
        ],
    }

    current = base.get("current_forecast")
    if current:
        current_rows = _segment(rows, program="2026-06-08")
        same_utils = [float(row["utilization"]) for row in current_rows[-8:]]
        factor = max(0.0, min(1.10, _median(same_utils, 1.0)))
        capacity = float(current["safe_harbour_capacity_shares"])
        remaining = int(current["remaining_program_shares"])
        base_case = min(float(remaining), capacity * factor)
        recent_capacity_errors = [
            abs(float(row["program_rolling_prediction"]) - float(row["actual_shares"]))
            / float(row["week_start_capacity_estimate_shares"])
            for row in current_rows[-8:]
            if float(row["week_start_capacity_estimate_shares"]) > 0
        ]
        band = _median(recent_capacity_errors, 0.12)
        # Week-start capacity is not a legal hard ceiling because each purchase day gets
        # a newly rolling 20-day ADV. Permit a conservative +10% forecast-band extension.
        upper_reference = min(float(remaining), capacity * 1.10)
        result["current_forecast_v2"] = {
            "period_start": current["period_start"],
            "period_end": current["period_end"],
            "adv20_shares": current["adv20_shares"],
            "week_start_capacity_estimate_shares": round(capacity),
            "remaining_program_shares": remaining,
            "last_close_nok": current["last_close_nok"],
            "program_price_limit_nok": current["program_price_limit_nok"],
            "price_state": current["price_state"],
            "program_utilization_factor": round(factor, 4),
            "base_case_shares": round(base_case),
            "range_low_shares": round(max(0.0, base_case - capacity * band)),
            "range_high_shares": round(min(upper_reference, base_case + capacity * band)),
            "confidence": "HIGH" if len(current_rows) >= 6 and current["price_state"] == "OPEN" else "MEDIUM",
            "methodology": "25% of prior-20-day ADV frozen at week start × trading days × median utilization of last 8 weeks in active program",
        }

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

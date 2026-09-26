"""Pure forecast calculations, mirrored in cloudflare/src/buyback_model.py.

The raw volume proxy is retained. Winsorisation is a forecasting assumption, not
an identification of block trades or a replacement for a legal volume limit.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

METHOD_VERSION = "otec-buyback-robust-volume-v2"
RECENT_EXECUTION_WEEKS = 4
OUTLIER_MEDIAN_MULTIPLE = 3.0


def known_history(history: list[dict[str, Any]], before: str) -> list[dict[str, Any]]:
    return [
        row
        for row in history
        if row["period_end"] < before
        and (not row.get("published_date") or row["published_date"] < before)
    ]


def point_estimate(
    lookback: list[Any],
    days: int,
    remaining: int,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    volumes = [float(row["volume_shares"]) for row in lookback]
    raw_adv = statistics.mean(volumes)
    cap = OUTLIER_MEDIAN_MULTIPLE * statistics.median(volumes)
    adjusted = [min(volume, cap) for volume in volumes]
    model_adv = statistics.mean(adjusted)
    raw_capacity = min(float(remaining), 0.25 * raw_adv * days)
    model_capacity = min(float(remaining), 0.25 * model_adv * days)

    recent = history[-RECENT_EXECUTION_WEEKS:]
    factor = 1.0
    if len(recent) >= 2:
        weights = range(1, len(recent) + 1)
        factor = sum(
            row["forecast_utilization"] * weight for row, weight in zip(recent, weights)
        ) / sum(weights)
    factor = max(0.0, min(1.10, factor))
    legacy_factor = (
        statistics.median(row["utilization"] for row in history[-8:])
        if len(history) >= 2
        else 1.0
    )
    legacy_factor = max(0.0, min(1.10, legacy_factor))
    return {
        "adv20_shares": raw_adv,
        "forecast_adv20_shares": model_adv,
        "week_start_capacity_estimate_shares": raw_capacity,
        "forecast_capacity_estimate_shares": model_capacity,
        "volume_outlier_days": sum(volume > cap for volume in volumes),
        "volume_adjustment_pct": (1 - model_adv / raw_adv) * 100 if raw_adv else 0.0,
        "walk_forward_factor": factor,
        "walk_forward_prediction_shares": min(
            float(remaining), model_capacity * factor
        ),
        "legacy_prediction_shares": min(float(remaining), raw_capacity * legacy_factor),
    }


def uncertainty_band(history: list[dict[str, Any]]) -> float:
    """80th percentile of prior absolute scaled errors, with a 12% floor.

    This is an empirical scenario range, not a calibrated confidence interval.
    """
    errors = sorted(
        row["absolute_error_shares"] / row["forecast_capacity_estimate_shares"]
        for row in history[-8:]
        if row["forecast_capacity_estimate_shares"] > 0
    )
    return max(0.12, errors[math.ceil(0.8 * len(errors)) - 1]) if errors else 0.20


def model_confidence(
    history: list[dict[str, Any]],
    price_state: str,
    volume_adjustment_pct: float,
) -> str:
    recent = history[-4:]
    actual = sum(row["actual_shares"] for row in recent)
    error = sum(row["absolute_error_shares"] for row in recent)
    wmape = error / actual if actual else None
    if price_state == "ABOVE_CAP" or len(recent) < 2 or wmape is None or wmape > 0.25:
        return "LOW"
    last = recent[-1]
    last_ape = (
        last["absolute_error_shares"] / last["actual_shares"]
        if last["actual_shares"]
        else 1.0
    )
    if (
        price_state == "OPEN"
        and len(history) >= 6
        and wmape <= 0.10
        and last_ape <= 0.20
        and volume_adjustment_pct <= 20
    ):
        return "HIGH"
    return "MEDIUM"

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

import brazil_dashboard as base

FOCUS_KEYS = ("selic", "ipca", "gdp", "usd_brl")


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _focus_point(values: Any, key: str, year: int) -> dict[str, Any] | None:
    if not isinstance(values, dict):
        return None
    by_year = values.get(key)
    if not isinstance(by_year, dict):
        return None
    point = by_year.get(str(year))
    return point if isinstance(point, dict) else None


def _comparison_points(
    current_values: Any,
    previous_values: Any,
    *,
    year: int,
) -> dict[str, Any]:
    points: dict[str, Any] = {}
    for key in FOCUS_KEYS:
        current = _focus_point(current_values, key, year)
        previous = _focus_point(previous_values, key, year)
        current_value = _finite((current or {}).get("median"))
        previous_value = _finite((previous or {}).get("median"))
        change = (
            current_value - previous_value
            if current_value is not None and previous_value is not None
            else None
        )
        points[key] = {
            "year": year,
            "current": current_value,
            "previous": previous_value,
            "change": change,
            "change_bp": change * 100 if change is not None and key in {"selic", "ipca"} else None,
            "current_survey_date": (current or {}).get("survey_date"),
            "previous_survey_date": (previous or {}).get("survey_date"),
        }
    return points


async def build_focus_trend(
    *,
    as_of_date: str,
    current_focus: Any,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compare current Focus medians with snapshots around 7 and 30 days earlier.

    The historical comparison reuses the same official BCB Olinda endpoint and the
    same parser as the live Focus card. Each comparison is independent so a missing
    historical response never blanks the current dashboard.
    """
    current_values = (
        current_focus.get("values")
        if isinstance(current_focus, dict) and isinstance(current_focus.get("values"), dict)
        else {}
    )
    target = date.fromisoformat(as_of_date)
    comparison_dates = {
        "7d": (target - timedelta(days=7)).isoformat(),
        "30d": (target - timedelta(days=30)).isoformat(),
    }

    async def load(label: str, target_date: str) -> tuple[str, str, dict[str, Any] | None, str | None]:
        try:
            payload = await base._load_focus(target_date, fetcher=fetcher)
            values = payload.get("values") if isinstance(payload, dict) else None
            if not isinstance(values, dict) or not values:
                raise ValueError("BCB Focus mangler historiske forventninger")
            return label, target_date, values, None
        except Exception as exc:  # noqa: BLE001 - comparisons are independent
            return label, target_date, None, f"{type(exc).__name__}: {exc}"

    loaded = await asyncio.gather(
        *(load(label, target_date) for label, target_date in comparison_dates.items())
    )
    year = target.year + 1
    comparisons: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for label, target_date, values, error in loaded:
        if values is None:
            errors[label] = str(error or "unknown error")
            comparisons[label] = {
                "ready": False,
                "target_date": target_date,
                "points": {},
            }
            continue
        comparisons[label] = {
            "ready": True,
            "target_date": target_date,
            "points": _comparison_points(current_values, values, year=year),
        }

    ready = any(bool(item.get("ready")) for item in comparisons.values())
    return (
        {
            "ready": ready,
            "comparison_year": year,
            "comparisons": comparisons,
            "source": "Banco Central do Brasil / Focus",
        },
        {
            "ready": ready,
            "comparison_dates": comparison_dates,
            "errors": errors,
        },
    )


def _tone_from_change(value: float | None, *, positive_when_lower: bool, threshold: float) -> str:
    if value is None or abs(value) < threshold:
        return "neutral"
    improved = value < 0 if positive_when_lower else value > 0
    return "positive" if improved else "negative"


def _tone_score(tone: str) -> int:
    if tone == "positive":
        return 1
    if tone == "negative":
        return -1
    return 0


def _metric_value(metrics: Any, key: str, field: str = "value") -> float | None:
    if not isinstance(metrics, dict) or not isinstance(metrics.get(key), dict):
        return None
    return _finite(metrics[key].get(field))


def _trend_change(focus_trend: Any, period: str, key: str) -> float | None:
    if not isinstance(focus_trend, dict):
        return None
    comparisons = focus_trend.get("comparisons")
    if not isinstance(comparisons, dict):
        return None
    comparison = comparisons.get(period)
    if not isinstance(comparison, dict):
        return None
    points = comparison.get("points")
    if not isinstance(points, dict) or not isinstance(points.get(key), dict):
        return None
    return _finite(points[key].get("change"))


def build_investor_summary(result: dict[str, Any], focus_trend: Any) -> dict[str, Any]:
    """Build a transparent three-channel Brazil view for an Otello investor."""
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    focus = result.get("focus") if isinstance(result.get("focus"), dict) else {}
    values = focus.get("values") if isinstance(focus.get("values"), dict) else {}
    as_of = str(result.get("as_of_date") or "")
    year = int(as_of[:4]) if len(as_of) >= 4 and as_of[:4].isdigit() else date.today().year

    selic_now = _metric_value(metrics, "selic")
    selic_current_year = _finite((_focus_point(values, "selic", year) or {}).get("median"))
    selic_next_year = _finite((_focus_point(values, "selic", year + 1) or {}).get("median"))
    expected_easing_bp = (
        (selic_next_year - selic_now) * 100
        if selic_now is not None and selic_next_year is not None
        else None
    )

    selic_30d = _trend_change(focus_trend, "30d", "selic")
    ipca_30d = _trend_change(focus_trend, "30d", "ipca")
    rate_tone = _tone_from_change(selic_30d, positive_when_lower=True, threshold=0.10)
    if rate_tone == "neutral" and expected_easing_bp is not None:
        if expected_easing_bp <= -50:
            rate_tone = "positive"
        elif expected_easing_bp >= 50:
            rate_tone = "negative"
    inflation_tone = _tone_from_change(ipca_30d, positive_when_lower=True, threshold=0.05)
    if rate_tone == "neutral" and inflation_tone != "neutral":
        rate_tone = inflation_tone

    activity_values = [
        value
        for value in (
            _metric_value(metrics, "ibc_br"),
            _metric_value(metrics, "ibc_services"),
        )
        if value is not None
    ]
    if len(activity_values) >= 2 and all(value > 0 for value in activity_values):
        activity_tone = "positive"
    elif len(activity_values) >= 2 and all(value < 0 for value in activity_values):
        activity_tone = "negative"
    else:
        activity_tone = "neutral"

    brl_change_1m = _metric_value(metrics, "brl_nok", "change_1m_pct")
    currency_tone = _tone_from_change(brl_change_1m, positive_when_lower=False, threshold=1.0)

    score = sum(_tone_score(tone) for tone in (rate_tone, activity_tone, currency_tone))
    if score >= 2:
        overall_tone = "positive"
        headline = "Makrobildet er i bedring"
    elif score <= -2:
        overall_tone = "negative"
        headline = "Makrobildet er blitt mer krevende"
    else:
        overall_tone = "neutral"
        headline = "Makrobildet er blandet"

    rate_summary = "Rentebanen er stabil i Focus."
    if selic_30d is not None:
        direction = "ned" if selic_30d < 0 else "opp" if selic_30d > 0 else "uendret"
        rate_summary = f"Neste års Selic-estimat er {direction} {abs(selic_30d) * 100:.0f} bp siste 30 dager."
    elif expected_easing_bp is not None:
        direction = "lavere" if expected_easing_bp < 0 else "høyere"
        rate_summary = f"Focus peker mot {abs(expected_easing_bp):.0f} bp {direction} rente enn i dag neste år."

    if activity_tone == "positive":
        activity_summary = "Både samlet aktivitet og tjenester viser positiv siste månedsutvikling."
    elif activity_tone == "negative":
        activity_summary = "Både samlet aktivitet og tjenester viser negativ siste månedsutvikling."
    else:
        activity_summary = "Aktivitetssignalene er blandede eller omtrent flate."

    if brl_change_1m is None:
        currency_summary = "Månedsendring i BRL/NOK er ikke tilgjengelig."
    else:
        currency_summary = f"BRL/NOK er {brl_change_1m:+.1f} % siste måned, med direkte effekt på Otellos Bemobi-verdi i NOK."

    return {
        "tone": overall_tone,
        "headline": headline,
        "score": score,
        "method": "Tre transparente kanaler: rentebane, økonomisk aktivitet og BRL/NOK. Ingen AI-score.",
        "drivers": {
            "valuation": {
                "tone": rate_tone,
                "label": "Verdsettelse",
                "summary": rate_summary,
            },
            "operations": {
                "tone": activity_tone,
                "label": "Bemobi-drift",
                "summary": activity_summary,
            },
            "nav_fx": {
                "tone": currency_tone,
                "label": "Otello NAV",
                "summary": currency_summary,
            },
        },
        "rate_path": {
            "current": selic_now,
            "current_year_estimate": selic_current_year,
            "next_year_estimate": selic_next_year,
            "expected_change_to_next_year_bp": expected_easing_bp,
        },
    }

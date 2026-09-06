from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection


HISTORY_DAYS = 365 * 5 + 10
MAX_LOOKBACK_DAYS = 7
SOURCE_PRIORITY = {
    "NORGES_BANK": 0,
    "ECB": 1,
}
SOURCE_URLS = {
    "NORGES_BANK": "https://www.norges-bank.no/tema/Statistikk/Valutakurser/",
    "ECB": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
}


def _pct_change(current: Decimal | None, reference: Decimal | None) -> float | None:
    if current is None or reference is None or reference == 0:
        return None
    return float((current / reference - Decimal("1")) * Decimal("100"))


def _preferred_series(
    connection,
    *,
    base_currency: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT substr(fr.observed_at, 1, 10) AS rate_date,
               fr.rate,
               s.code AS source_code
        FROM fx_rates fr
        JOIN sources s ON s.id = fr.source_id
        WHERE fr.base_currency = ?
          AND fr.quote_currency = 'NOK'
          AND substr(fr.observed_at, 1, 10) BETWEEN ? AND ?
          AND CAST(fr.rate AS REAL) > 0
        ORDER BY rate_date,
                 CASE s.code
                   WHEN 'NORGES_BANK' THEN 0
                   WHEN 'ECB' THEN 1
                   ELSE 5
                 END,
                 fr.observed_at DESC,
                 fr.id DESC
        """,
        (base_currency, start_date, end_date),
    ).fetchall()

    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row["rate_date"])
        if day in by_date:
            continue
        by_date[day] = {
            "date": day,
            "rate": Decimal(str(row["rate"])),
            "source_code": str(row["source_code"]),
        }
    return list(by_date.values())


def _on_or_before(
    series: list[dict[str, Any]],
    target_date: str,
    *,
    max_lookback_days: int | None = None,
) -> dict[str, Any] | None:
    if not series:
        return None
    dates = [str(item["date"]) for item in series]
    index = bisect_right(dates, target_date) - 1
    if index < 0:
        return None
    item = series[index]
    if max_lookback_days is not None:
        distance = date.fromisoformat(target_date) - date.fromisoformat(str(item["date"]))
        if distance.days > max_lookback_days:
            return None
    return item


def _reference_date(current_date: str, period: str) -> str:
    current = date.fromisoformat(current_date)
    if period == "d1":
        return (current - timedelta(days=1)).isoformat()
    if period == "m1":
        return (current - timedelta(days=30)).isoformat()
    if period == "ytd":
        return date(current.year, 1, 1).isoformat()
    if period == "y1":
        return (current - timedelta(days=365)).isoformat()
    if period == "y3":
        return (current - timedelta(days=365 * 3)).isoformat()
    return (current - timedelta(days=365 * 5)).isoformat()


def _period_snapshot(
    *,
    period: str,
    current_date: str,
    brl_series: list[dict[str, Any]],
    usd_series: list[dict[str, Any]],
) -> dict[str, Any]:
    current_brl = _on_or_before(brl_series, current_date)
    current_usd = _on_or_before(
        usd_series,
        current_date,
        max_lookback_days=MAX_LOOKBACK_DAYS,
    )
    target = _reference_date(current_date, period)
    reference_brl = _on_or_before(brl_series, target)
    reference_usd = _on_or_before(
        usd_series,
        reference_brl["date"] if reference_brl is not None else target,
        max_lookback_days=MAX_LOOKBACK_DAYS,
    )

    if current_brl is None or reference_brl is None:
        return {
            "reference_date": None,
            "brl_nok_pct": None,
            "usd_nok_pct": None,
            "usd_brl_pct": None,
        }

    current_brl_rate = Decimal(str(current_brl["rate"]))
    reference_brl_rate = Decimal(str(reference_brl["rate"]))
    usd_nok_pct = None
    usd_brl_pct = None
    if current_usd is not None and reference_usd is not None:
        current_usd_rate = Decimal(str(current_usd["rate"]))
        reference_usd_rate = Decimal(str(reference_usd["rate"]))
        usd_nok_pct = _pct_change(current_usd_rate, reference_usd_rate)
        current_cross = current_usd_rate / current_brl_rate
        reference_cross = reference_usd_rate / reference_brl_rate
        usd_brl_pct = _pct_change(current_cross, reference_cross)

    return {
        "reference_date": reference_brl["date"],
        "brl_nok_pct": _pct_change(current_brl_rate, reference_brl_rate),
        "usd_nok_pct": usd_nok_pct,
        "usd_brl_pct": usd_brl_pct,
    }


def _range_stats(series: list[dict[str, Any]], *, start_date: str) -> dict[str, float | None]:
    values = [
        Decimal(str(item["rate"]))
        for item in series
        if str(item["date"]) >= start_date
    ]
    if not values:
        return {"low": None, "high": None, "average": None, "percentile": None}
    current = values[-1]
    low = min(values)
    high = max(values)
    average = sum(values, Decimal("0")) / Decimal(len(values))
    below_or_equal = sum(1 for value in values if value <= current)
    percentile = Decimal(below_or_equal) / Decimal(len(values)) * Decimal("100")
    return {
        "low": float(low),
        "high": float(high),
        "average": float(average),
        "percentile": float(percentile),
    }


def fx_dashboard(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        latest = connection.execute(
            """
            SELECT MAX(substr(observed_at, 1, 10)) AS max_date
            FROM fx_rates
            WHERE base_currency = 'BRL'
              AND quote_currency = 'NOK'
              AND CAST(rate AS REAL) > 0
            """
        ).fetchone()
        if latest is None or latest["max_date"] is None:
            return {"ready": False, "reason": "missing_brl_nok_history", "series": []}

        end_date = str(latest["max_date"])
        start_date = (date.fromisoformat(end_date) - timedelta(days=HISTORY_DAYS)).isoformat()
        brl_series = _preferred_series(
            connection,
            base_currency="BRL",
            start_date=start_date,
            end_date=end_date,
        )
        usd_series = _preferred_series(
            connection,
            base_currency="USD",
            start_date=start_date,
            end_date=end_date,
        )

    current_brl = _on_or_before(brl_series, end_date)
    current_usd = _on_or_before(
        usd_series,
        end_date,
        max_lookback_days=MAX_LOOKBACK_DAYS,
    )
    if current_brl is None:
        return {"ready": False, "reason": "missing_brl_nok_history", "series": []}

    points: list[dict[str, Any]] = []
    source_codes: set[str] = set()
    for brl in brl_series:
        usd = _on_or_before(
            usd_series,
            str(brl["date"]),
            max_lookback_days=MAX_LOOKBACK_DAYS,
        )
        brl_rate = Decimal(str(brl["rate"]))
        usd_rate = Decimal(str(usd["rate"])) if usd is not None else None
        source_codes.add(str(brl["source_code"]))
        if usd is not None:
            source_codes.add(str(usd["source_code"]))
        points.append(
            {
                "date": brl["date"],
                "brl_nok": float(brl_rate),
                "usd_nok": float(usd_rate) if usd_rate is not None else None,
                "usd_brl": float(usd_rate / brl_rate) if usd_rate is not None else None,
            }
        )

    current_brl_rate = Decimal(str(current_brl["rate"]))
    current_usd_rate = Decimal(str(current_usd["rate"])) if current_usd is not None else None
    periods = {
        period: _period_snapshot(
            period=period,
            current_date=end_date,
            brl_series=brl_series,
            usd_series=usd_series,
        )
        for period in ("d1", "m1", "ytd", "y1", "y3", "y5")
    }
    one_year_start = (date.fromisoformat(end_date) - timedelta(days=365)).isoformat()

    return {
        "ready": True,
        "as_of_date": end_date,
        "current": {
            "brl_nok": float(current_brl_rate),
            "usd_nok": float(current_usd_rate) if current_usd_rate is not None else None,
            "usd_brl": (
                float(current_usd_rate / current_brl_rate)
                if current_usd_rate is not None
                else None
            ),
        },
        "periods": periods,
        "range_1y": _range_stats(brl_series, start_date=one_year_start),
        "series": points,
        "sources": [
            {
                "code": code,
                "name": "Norges Bank" if code == "NORGES_BANK" else "ECB" if code == "ECB" else code,
                "url": SOURCE_URLS.get(code),
            }
            for code in sorted(source_codes, key=lambda code: SOURCE_PRIORITY.get(code, 5))
        ],
        "method_note": (
            "BRL/NOK og USD/NOK bruker én prioritert observasjon per dato, med Norges Bank foran ECB. "
            "USD/BRL er avledet som USD/NOK delt på BRL/NOK."
        ),
    }

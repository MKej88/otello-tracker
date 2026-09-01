from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.db.connection import get_connection
from app.nav.daily_nav import CALCULATION_VERSION as CORE_CALCULATION_VERSION
from app.nav.full_nav import FULL_CALCULATION_VERSION
from app.nav_waterfall_attribution import symmetric_two_factor_attribution


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


def _pct_change(current: Any, previous: Any) -> float | None:
    if current is None or previous is None:
        return None
    old = Decimal(str(previous))
    if old == 0:
        return None
    return float((Decimal(str(current)) / old - Decimal("1")) * Decimal("100"))


def _brl_observations(connection, *, end_date: str) -> list[dict[str, Any]]:
    """Return one preferred, valid BRL/NOK observation per day."""
    start_date = (date.fromisoformat(end_date) - timedelta(days=365)).isoformat()
    rows = connection.execute(
        """
        SELECT substr(fr.observed_at, 1, 10) AS rate_date, fr.rate
        FROM fx_rates fr JOIN sources s ON s.id=fr.source_id
        WHERE fr.base_currency='BRL' AND fr.quote_currency='NOK'
          AND substr(fr.observed_at, 1, 10) BETWEEN ? AND ?
          AND CAST(fr.rate AS REAL) > 0
        ORDER BY rate_date,
          CASE s.code WHEN 'NORGES_BANK' THEN 0 WHEN 'ECB' THEN 1 ELSE 5 END,
          fr.observed_at DESC, fr.id DESC
        """,
        (start_date, end_date),
    ).fetchall()
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row["rate_date"])
        if day not in by_date:
            by_date[day] = {"date": day, "rate": Decimal(str(row["rate"]))}
    return list(by_date.values())


def _on_or_before(
    observations: list[dict[str, Any]], target_date: str
) -> dict[str, Any] | None:
    return next(
        (item for item in reversed(observations) if item["date"] <= target_date),
        None,
    )


def _quarter_label(day: str) -> str:
    parsed = date.fromisoformat(day)
    return f"Q{(parsed.month - 1) // 3 + 1} {str(parsed.year)[2:]}"


def nav_discount_metrics(
    *,
    nav_per_share: Any,
    share_price: Any,
    current_date: str,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate null-safe discount context from the existing daily NAV series."""
    try:
        nav = float(nav_per_share)
    except (TypeError, ValueError):
        nav = math.nan
    try:
        price = float(share_price)
    except (TypeError, ValueError):
        price = math.nan
    valid_nav = math.isfinite(nav) and nav > 0
    valid_price = math.isfinite(price) and price > 0
    valid_current = valid_nav and valid_price
    current_discount = (1 - price / nav) * 100 if valid_current else None
    upside = (nav / price - 1) * 100 if valid_current else None

    start_date = (date.fromisoformat(current_date) - timedelta(days=365)).isoformat()
    valid: list[dict[str, Any]] = []
    for item in observations:
        raw = item.get("discount_pct")
        try:
            discount = float(raw)
        except (TypeError, ValueError):
            continue
        item_date = str(item.get("date") or "")
        if math.isfinite(discount) and start_date <= item_date <= current_date:
            valid.append({"date": item_date, "discount_pct": discount})
    valid.sort(key=lambda item: item["date"])

    reference_date = (date.fromisoformat(current_date) - timedelta(days=30)).isoformat()
    reference = _on_or_before(valid, reference_date)
    values = [item["discount_pct"] for item in valid]
    low = min(values) if values else None
    high = max(values) if values else None
    position = None
    if current_discount is not None and low is not None and high is not None:
        position = (
            50.0 if high == low else (current_discount - low) / (high - low) * 100
        )

    return {
        "nav_per_share": nav if valid_nav else None,
        "share_price": price if valid_price else None,
        "discount_pct": current_discount,
        "upside_to_nav_pct": upside,
        "month_change_pp": (
            current_discount - reference["discount_pct"]
            if current_discount is not None and reference is not None
            else None
        ),
        "month_reference_date": reference["date"] if reference else None,
        "median_1y_pct": statistics.median(values) if values else None,
        "range_1y": {"low": low, "high": high, "position_pct": position},
    }


def _nav_discount_insights(
    connection, *, calculation_version: str, nav_scope: str, latest
) -> dict[str, Any]:
    current_date = str(latest["as_of_at"])[:10]
    start_date = (date.fromisoformat(current_date) - timedelta(days=365)).isoformat()
    rows = connection.execute(
        """
        SELECT substr(as_of_at, 1, 10) AS date, discount_pct
        FROM nav_snapshots
        WHERE calculation_version = ? AND nav_scope = ?
          AND substr(as_of_at, 1, 10) BETWEEN ? AND ?
        ORDER BY as_of_at
        """,
        (calculation_version, nav_scope, start_date, current_date),
    ).fetchall()
    by_date = {str(row["date"]): dict(row) for row in rows}
    return nav_discount_metrics(
        nav_per_share=latest["nav_per_share_nok"],
        share_price=latest["otec_price_nok"],
        current_date=current_date,
        observations=list(by_date.values()),
    )


def _brl_nav_effect_30d(
    connection,
    *,
    reference_date: str,
    as_of_date: str,
    reference_fx: Decimal,
    current_fx: Decimal,
) -> float | None:
    """Use the NAV driver's symmetric price/FX attribution for a 30-day bridge."""
    from app.nav.daily_nav import _holding, _preferred_price

    reference_price = _preferred_price(connection, "BMOB3", reference_date)
    current_price = _preferred_price(connection, "BMOB3", as_of_date)
    reference_holding = _holding(connection, reference_date)
    current_holding = _holding(connection, as_of_date)
    shares_row = connection.execute(
        """
        SELECT shares_outstanding FROM nav_snapshots
        WHERE substr(as_of_at, 1, 10) <= ? AND shares_outstanding > 0
        ORDER BY as_of_at DESC, id DESC LIMIT 1
        """,
        (reference_date,),
    ).fetchone()
    if any(
        value is None
        for value in (
            reference_price,
            current_price,
            reference_holding,
            current_holding,
            shares_row,
        )
    ):
        return None
    if int(reference_holding["shares"]) != int(current_holding["shares"]):
        return None
    attribution = symmetric_two_factor_attribution(
        shares=int(reference_holding["shares"]),
        anchor_price=Decimal(str(reference_price["price"])),
        current_price=Decimal(str(current_price["price"])),
        anchor_fx=reference_fx,
        current_fx=current_fx,
    )
    return float(
        attribution["fx_effect_nok"] / Decimal(shares_row["shares_outstanding"])
    )


def brl_nok_insights(connection, *, as_of_date: str) -> dict[str, Any]:
    """Build compact, null-safe investor metrics from the existing FX history."""
    observations = _brl_observations(connection, end_date=as_of_date)
    current = _on_or_before(observations, as_of_date)
    if current is None:
        return {
            "daily_pct": None,
            "month_pct": None,
            "quarter_pct": None,
            "quarter_label": None,
            "nav_effect_1m_per_share_nok": None,
            "range_1y": {"low": None, "high": None, "position_pct": None},
        }

    current_index = observations.index(current)
    previous = observations[current_index - 1] if current_index > 0 else None
    month_target = (
        date.fromisoformat(current["date"]) - timedelta(days=30)
    ).isoformat()
    month_reference = _on_or_before(observations, month_target)
    anchor = connection.execute(
        """
        SELECT as_of_date FROM cash_anchors
        WHERE anchor_type='REPORTED' AND as_of_date <= ?
        ORDER BY as_of_date DESC, id DESC LIMIT 1
        """,
        (current["date"],),
    ).fetchone()
    anchor_date = str(anchor["as_of_date"]) if anchor is not None else None
    quarter_reference = (
        _on_or_before(observations, anchor_date) if anchor_date else None
    )
    rates = [item["rate"] for item in observations]
    low = min(rates)
    high = max(rates)
    position = (
        None
        if high == low
        else float((current["rate"] - low) / (high - low) * Decimal("100"))
    )
    nav_effect = (
        _brl_nav_effect_30d(
            connection,
            reference_date=month_reference["date"],
            as_of_date=current["date"],
            reference_fx=month_reference["rate"],
            current_fx=current["rate"],
        )
        if month_reference is not None
        else None
    )
    return {
        "daily_pct": _pct_change(
            current["rate"], previous["rate"] if previous else None
        ),
        "month_pct": _pct_change(
            current["rate"], month_reference["rate"] if month_reference else None
        ),
        "month_reference_date": month_reference["date"] if month_reference else None,
        "quarter_pct": _pct_change(
            current["rate"], quarter_reference["rate"] if quarter_reference else None
        ),
        "quarter_label": _quarter_label(anchor_date) if anchor_date else None,
        "quarter_reference_date": (
            quarter_reference["date"] if quarter_reference else None
        ),
        "nav_effect_1m_per_share_nok": nav_effect,
        "range_1y": {
            "low": float(low),
            "high": float(high),
            "position_pct": position,
        },
    }


def _bmob3_observations(connection, *, end_date: str) -> list[dict[str, Any]]:
    """Return one preferred, valid BMOB3 close per trading day."""
    start_date = (date.fromisoformat(end_date) - timedelta(days=365)).isoformat()
    rows = connection.execute(
        """
        SELECT mp.trading_date AS date, mp.price
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol='BMOB3' AND mp.price_type IN ('CLOSE', 'LAST')
          AND mp.trading_date BETWEEN ? AND ? AND CAST(mp.price AS REAL) > 0
        ORDER BY mp.trading_date,
          CASE s.code WHEN 'B3' THEN 0 WHEN 'INVESTING' THEN 2 ELSE 5 END,
          CASE mp.price_type WHEN 'CLOSE' THEN 0 ELSE 1 END,
          CASE mp.quality WHEN 'DIRECT' THEN 0 ELSE 1 END,
          mp.observed_at DESC, mp.id DESC
        """,
        (start_date, end_date),
    ).fetchall()
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row["date"])
        if day not in by_date:
            by_date[day] = {"date": day, "price": Decimal(str(row["price"]))}
    return list(by_date.values())


def bemobi_insights(
    connection,
    *,
    as_of_date: str,
    bemobi_value_nok: Any,
    shares_outstanding: Any,
) -> dict[str, Any]:
    """Build BMOB3 performance and exposure from existing NAV inputs."""
    observations = _bmob3_observations(connection, end_date=as_of_date)
    current = _on_or_before(observations, as_of_date)
    empty_range = {"low": None, "high": None, "position_pct": None}
    if current is None:
        return {
            "price_brl": None,
            "price_date": None,
            "daily_pct": None,
            "month_pct": None,
            "quarter_pct": None,
            "quarter_label": None,
            "nav_effect_1m_per_share_nok": None,
            "value_per_otec_share_nok": None,
            "holding_shares": None,
            "ownership_pct": None,
            "range_1y": empty_range,
        }

    current_index = observations.index(current)
    previous = observations[current_index - 1] if current_index > 0 else None
    month_target = (
        date.fromisoformat(current["date"]) - timedelta(days=30)
    ).isoformat()
    month_reference = _on_or_before(observations, month_target)
    anchor = connection.execute(
        """SELECT as_of_date FROM cash_anchors
        WHERE anchor_type='REPORTED' AND as_of_date <= ?
        ORDER BY as_of_date DESC, id DESC LIMIT 1""",
        (current["date"],),
    ).fetchone()
    anchor_date = str(anchor["as_of_date"]) if anchor is not None else None
    quarter_reference = (
        _on_or_before(observations, anchor_date) if anchor_date else None
    )
    holding = connection.execute(
        """SELECT shares, ownership_pct FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC LIMIT 1""",
        (current["date"], current["date"]),
    ).fetchone()

    nav_effect = None
    if month_reference is not None and holding is not None:
        reference_holding = connection.execute(
            """SELECT shares FROM bemobi_holdings
            WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
            ORDER BY effective_from DESC, id DESC LIMIT 1""",
            (month_reference["date"], month_reference["date"]),
        ).fetchone()
        fx_observations = _brl_observations(connection, end_date=current["date"])
        reference_fx = _on_or_before(fx_observations, month_reference["date"])
        current_fx = _on_or_before(fx_observations, current["date"])
        if (
            reference_fx is not None
            and current_fx is not None
            and reference_holding is not None
            and int(reference_holding["shares"]) == int(holding["shares"])
        ):
            attribution = symmetric_two_factor_attribution(
                shares=int(holding["shares"]),
                anchor_price=month_reference["price"],
                current_price=current["price"],
                anchor_fx=reference_fx["rate"],
                current_fx=current_fx["rate"],
            )
            try:
                outstanding = Decimal(str(shares_outstanding))
            except (InvalidOperation, TypeError, ValueError):
                outstanding = Decimal("0")
            if outstanding.is_finite() and outstanding > 0:
                nav_effect = float(attribution["price_effect_nok"] / outstanding)

    prices = [item["price"] for item in observations]
    low, high = min(prices), max(prices)
    position = (
        None
        if high == low
        else float((current["price"] - low) / (high - low) * Decimal("100"))
    )
    try:
        value = Decimal(str(bemobi_value_nok))
        outstanding = Decimal(str(shares_outstanding))
        value_per_share = (
            float(value / outstanding)
            if value.is_finite() and outstanding.is_finite() and outstanding > 0
            else None
        )
    except (InvalidOperation, TypeError, ValueError):
        value_per_share = None
    return {
        "price_brl": float(current["price"]),
        "price_date": current["date"],
        "daily_pct": _pct_change(
            current["price"], previous["price"] if previous else None
        ),
        "month_pct": _pct_change(
            current["price"], month_reference["price"] if month_reference else None
        ),
        "month_reference_date": month_reference["date"] if month_reference else None,
        "quarter_pct": _pct_change(
            current["price"], quarter_reference["price"] if quarter_reference else None
        ),
        "quarter_label": _quarter_label(anchor_date) if anchor_date else None,
        "quarter_reference_date": (
            quarter_reference["date"] if quarter_reference else None
        ),
        "nav_effect_1m_per_share_nok": nav_effect,
        "value_per_otec_share_nok": value_per_share,
        "holding_shares": int(holding["shares"]) if holding is not None else None,
        "ownership_pct": (
            _float(holding["ownership_pct"]) if holding is not None else None
        ),
        "range_1y": {
            "low": float(low),
            "high": float(high),
            "position_pct": position,
        },
    }


def _components(row) -> dict[str, Any]:
    raw = row["components_json"] if row is not None else None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def _latest_series_date(
    connection, calculation_version: str, nav_scope: str
) -> str | None:
    row = connection.execute(
        """
        SELECT MAX(substr(as_of_at, 1, 10)) AS max_date
        FROM nav_snapshots
        WHERE calculation_version = ? AND nav_scope = ?
        """,
        (calculation_version, nav_scope),
    ).fetchone()
    return row["max_date"] if row is not None else None


def _preferred_nav_series(connection) -> tuple[str, str]:
    """Prefer FULL only when it is current with the latest CORE snapshot.

    FULL is derived from CORE. If a downstream ONA/FULL rebuild fails, old FULL rows may
    legitimately remain in SQLite while CORE has advanced. Returning that older FULL row
    would make the dashboard look current while silently displaying stale NAV, so CORE is
    preferred whenever the two series do not end on the same date.
    """
    core_date = _latest_series_date(connection, CORE_CALCULATION_VERSION, "CORE")
    full_date = _latest_series_date(connection, FULL_CALCULATION_VERSION, "FULL")

    if full_date is not None and core_date == full_date:
        return FULL_CALCULATION_VERSION, "FULL"
    if core_date is not None:
        return CORE_CALCULATION_VERSION, "CORE"
    if full_date is not None:
        return FULL_CALCULATION_VERSION, "FULL"
    return CORE_CALCULATION_VERSION, "CORE"


def _core_components_for_date(connection, as_of_at: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT components_json FROM nav_snapshots
        WHERE as_of_at = ? AND calculation_version = ? AND nav_scope = 'CORE'
        LIMIT 1
        """,
        (as_of_at, CORE_CALCULATION_VERSION),
    ).fetchone()
    return _components(row)


def dashboard_summary(database_path: str | None = None) -> dict[str, Any]:
    """Return latest real KPIs, preferring current FULL NAV and safely falling back to CORE."""
    with get_connection(database_path) as connection:
        calculation_version, model_scope = _preferred_nav_series(connection)
        rows = connection.execute(
            """
            SELECT as_of_at, nav_per_share_nok, otec_price_nok, discount_pct,
                   bemobi_value_nok, cash_estimate_nok, other_net_assets_nok,
                   shares_outstanding, status, components_json, quality_notes
            FROM nav_snapshots
            WHERE calculation_version = ? AND nav_scope = ?
            ORDER BY as_of_at DESC LIMIT 2
            """,
            (calculation_version, model_scope),
        ).fetchall()

        if not rows:
            return {
                "ready": False,
                "data_status": "not_ready",
                "model_scope": "CORE",
                "calculation_version": CORE_CALCULATION_VERSION,
                "message": "Kjør markedsdata-backfill og NAV-rebuild for å fylle dashboardet.",
            }

        latest = rows[0]
        previous = rows[1] if len(rows) > 1 else None
        if model_scope == "FULL":
            current_components = _core_components_for_date(
                connection, latest["as_of_at"]
            )
            previous_components = (
                _core_components_for_date(connection, previous["as_of_at"])
                if previous is not None
                else {}
            )
        else:
            current_components = _components(latest)
            previous_components = _components(previous)

        bmob3 = current_components.get("bmob3", {})
        previous_bmob3 = previous_components.get("bmob3", {})
        cash = current_components.get("cash", {})
        otec = current_components.get("otec", {})

        as_of_date = str(latest["as_of_at"])[:10]
        holding = connection.execute(
            """
            SELECT shares, ownership_pct FROM bemobi_holdings
            WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
            ORDER BY effective_from DESC, id DESC LIMIT 1
            """,
            (as_of_date, as_of_date),
        ).fetchone()
        latest_buyback = connection.execute(
            """
            SELECT trade_date, shares, avg_price_nok, amount_nok,
                   treasury_shares_after, cumulative_program_shares,
                   cumulative_program_amount_nok
            FROM buybacks
            WHERE trade_date <= ?
            ORDER BY trade_date DESC, id DESC LIMIT 1
            """,
            (as_of_date,),
        ).fetchone()
        latest_share_count_row = connection.execute(
            """
            SELECT sc.effective_from, sc.total_shares, sc.treasury_shares,
                   sc.outstanding_shares, sc.source_document_id,
                   s.code AS source_code, sd.url AS source_url
            FROM otello_share_counts sc
            LEFT JOIN source_documents sd ON sd.id=sc.source_document_id
            LEFT JOIN sources s ON s.id=sd.source_id
            WHERE sc.effective_from <= ?
            ORDER BY sc.effective_from DESC, sc.id DESC LIMIT 1
            """,
            (as_of_date,),
        ).fetchone()
        latest_share_count = None
        if latest_share_count_row is not None:
            nav_outstanding = int(latest["shares_outstanding"])
            latest_share_count = {
                "effective_from": latest_share_count_row["effective_from"],
                "total_shares": int(latest_share_count_row["total_shares"]),
                "treasury_shares": int(latest_share_count_row["treasury_shares"]),
                "outstanding_shares": int(latest_share_count_row["outstanding_shares"]),
                "source_document_id": latest_share_count_row["source_document_id"],
                "source_code": latest_share_count_row["source_code"],
                "source_url": latest_share_count_row["source_url"],
                "used_in_nav": int(latest_share_count_row["outstanding_shares"])
                == nav_outstanding,
            }

        nav_change = _pct_change(
            latest["nav_per_share_nok"],
            previous["nav_per_share_nok"] if previous else None,
        )
        otec_change = _pct_change(
            latest["otec_price_nok"], previous["otec_price_nok"] if previous else None
        )
        discount_change = (
            float(
                Decimal(str(latest["discount_pct"]))
                - Decimal(str(previous["discount_pct"]))
            )
            if previous is not None
            and latest["discount_pct"] is not None
            and previous["discount_pct"] is not None
            else None
        )
        bmob3_change = _pct_change(
            bmob3.get("price_brl"), previous_bmob3.get("price_brl")
        )
        brl_change = _pct_change(bmob3.get("brl_nok"), previous_bmob3.get("brl_nok"))
        cash_change = _pct_change(
            latest["cash_estimate_nok"],
            previous["cash_estimate_nok"] if previous else None,
        )

        return {
            "ready": True,
            "data_status": latest["status"],
            "model_scope": model_scope,
            "calculation_version": calculation_version,
            "as_of_date": as_of_date,
            "nav_per_share": _float(latest["nav_per_share_nok"]),
            "otec_price": _float(latest["otec_price_nok"]),
            "nav_discount_pct": _float(latest["discount_pct"]),
            "nav_discount_insights": _nav_discount_insights(
                connection,
                calculation_version=calculation_version,
                nav_scope=model_scope,
                latest=latest,
            ),
            "bmob3_price": _float(bmob3.get("price_brl")),
            "brl_nok": _float(bmob3.get("brl_nok")),
            "brl_nok_insights": brl_nok_insights(connection, as_of_date=as_of_date),
            "bemobi_insights": bemobi_insights(
                connection,
                as_of_date=as_of_date,
                bemobi_value_nok=latest["bemobi_value_nok"],
                shares_outstanding=latest["shares_outstanding"],
            ),
            "estimated_cash_mnok": (
                _float(latest["cash_estimate_nok"]) / 1_000_000
                if latest["cash_estimate_nok"] is not None
                else None
            ),
            "other_net_assets_mnok": (
                _float(latest["other_net_assets_nok"]) / 1_000_000
                if latest["other_net_assets_nok"] is not None
                else None
            ),
            "bemobi_value_mnok": (
                _float(latest["bemobi_value_nok"]) / 1_000_000
                if latest["bemobi_value_nok"] is not None
                else None
            ),
            "bemobi_shares": int(holding["shares"]) if holding is not None else None,
            "bemobi_ownership_pct": (
                _float(holding["ownership_pct"]) if holding is not None else None
            ),
            "shares_outstanding": int(latest["shares_outstanding"]),
            "share_count": latest_share_count,
            "cash_quality": cash.get("quality"),
            "cash_calibration_quality": cash.get("calibration_quality"),
            "share_count_quality": otec.get("share_count_quality"),
            "otec_price_quality": otec.get("price_quality"),
            "otec_price_source": otec.get("price_source"),
            "bmob3_price_quality": bmob3.get("price_quality"),
            "bmob3_price_source": bmob3.get("price_source"),
            "quality_notes": latest["quality_notes"],
            "changes": {
                "nav_pct": nav_change,
                "otec_pct": otec_change,
                "discount_pp": discount_change,
                "bmob3_pct": bmob3_change,
                "brl_nok_pct": brl_change,
                "cash_pct": cash_change,
            },
            "latest_buyback": (
                dict(latest_buyback) if latest_buyback is not None else None
            ),
        }


def dashboard_history(
    database_path: str | None = None,
    *,
    days: int = 365,
    max_points: int = 400,
) -> dict[str, Any]:
    """Return bounded NAV/OTEC/discount history, preferring current FULL where available."""
    days = max(7, min(int(days), 3650))
    max_points = max(50, min(int(max_points), 1000))

    with get_connection(database_path) as connection:
        calculation_version, model_scope = _preferred_nav_series(connection)
        latest = connection.execute(
            """
            SELECT MAX(substr(as_of_at,1,10)) AS max_date FROM nav_snapshots
            WHERE calculation_version = ? AND nav_scope = ?
            """,
            (calculation_version, model_scope),
        ).fetchone()
        if latest is None or latest["max_date"] is None:
            return {
                "ready": False,
                "data_status": "not_ready",
                "model_scope": model_scope,
                "calculation_version": calculation_version,
                "points": [],
            }

        end_date = date.fromisoformat(latest["max_date"])
        start_date = end_date - timedelta(days=days - 1)
        rows = connection.execute(
            """
            SELECT substr(as_of_at,1,10) AS date, nav_per_share_nok,
                   otec_price_nok, discount_pct, cash_estimate_nok,
                   other_net_assets_nok, status
            FROM nav_snapshots
            WHERE calculation_version = ? AND nav_scope = ?
              AND substr(as_of_at,1,10) >= ? AND substr(as_of_at,1,10) <= ?
            ORDER BY as_of_at
            """,
            (
                calculation_version,
                model_scope,
                start_date.isoformat(),
                end_date.isoformat(),
            ),
        ).fetchall()

    raw = [
        {
            "date": row["date"],
            "nav_per_share": _float(row["nav_per_share_nok"]),
            "otec_price": _float(row["otec_price_nok"]),
            "discount_pct": _float(row["discount_pct"]),
            "cash_mnok": _float(row["cash_estimate_nok"]) / 1_000_000,
            "other_net_assets_mnok": _float(row["other_net_assets_nok"]) / 1_000_000,
            "status": row["status"],
        }
        for row in rows
    ]

    if len(raw) > max_points:
        step = (len(raw) - 1) / (max_points - 1)
        indices = sorted({round(i * step) for i in range(max_points)})
        points = [raw[index] for index in indices]
        if points[-1]["date"] != raw[-1]["date"]:
            points[-1] = raw[-1]
    else:
        points = raw

    discounts = [
        Decimal(str(item["discount_pct"]))
        for item in raw
        if item["discount_pct"] is not None
    ]
    average_discount = (
        float(sum(discounts, Decimal("0")) / Decimal(len(discounts)))
        if discounts
        else None
    )

    return {
        "ready": bool(points),
        "data_status": points[-1]["status"] if points else "not_ready",
        "model_scope": model_scope,
        "calculation_version": calculation_version,
        "from": points[0]["date"] if points else None,
        "to": points[-1]["date"] if points else None,
        "raw_count": len(raw),
        "point_count": len(points),
        "average_discount_pct": average_discount,
        "points": points,
    }

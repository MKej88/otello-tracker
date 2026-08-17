from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text
from app.history.cash_events_2022 import seed_2022_cash_events
from app.history.distributions import seed_bemobi_distributions

MAX_LOOKBACK_DAYS = 7
_BUYBACK_PERIOD_RE = re.compile(r"during\s+(20\d{2}-\d{2}-\d{2})[–-](20\d{2}-\d{2}-\d{2})", re.I)


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _nearest_fx(connection, base: str, as_of_date: str):
    floor_date = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT id, substr(observed_at, 1, 10) AS rate_date, rate
        FROM fx_rates
        WHERE base_currency = ? AND quote_currency = 'NOK'
          AND substr(observed_at, 1, 10) <= ?
          AND substr(observed_at, 1, 10) >= ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (base, as_of_date, floor_date),
    ).fetchone()


def _holding(connection, as_of_date: str):
    return connection.execute(
        """
        SELECT id, shares, effective_from, effective_to
        FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (as_of_date, as_of_date),
    ).fetchone()


def _reported_anchors_nok(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, as_of_date, reported_amount, reported_currency, source_document_id
        FROM cash_anchors
        WHERE anchor_type = 'REPORTED'
        ORDER BY as_of_date
        """
    ).fetchall()
    anchors: list[dict[str, Any]] = []
    for row in rows:
        currency = row["reported_currency"]
        amount = Decimal(row["reported_amount"])
        if currency == "NOK":
            rate = Decimal("1")
            fx_id = None
            fx_date = row["as_of_date"]
        else:
            fx = _nearest_fx(connection, currency, row["as_of_date"])
            if fx is None:
                continue
            rate = Decimal(fx["rate"])
            fx_id = fx["id"]
            fx_date = fx["rate_date"]
        anchors.append(
            {
                "id": row["id"],
                "date": row["as_of_date"],
                "reported_amount": str(amount),
                "currency": currency,
                "fx_rate": str(rate),
                "fx_id": fx_id,
                "fx_date": fx_date,
                "cash_nok": amount * rate,
                "source_document_id": row["source_document_id"],
            }
        )
    return anchors


def sync_corporate_action_cash_movements(database_path: str | None = None) -> dict[str, int]:
    """Derive cash movements from corporate actions without pretending gross equals net."""
    seed_bemobi_distributions(database_path)
    written = 0
    updated = 0
    with get_connection(database_path) as connection:
        actions = connection.execute(
            """
            SELECT ca.*, i.symbol
            FROM corporate_actions ca
            JOIN instruments i ON i.id = ca.issuer_instrument_id
            WHERE ca.payment_date IS NOT NULL
              AND (
                (i.symbol = 'OTEC' AND ca.action_type = 'DISTRIBUTION') OR
                (i.symbol = 'BMOB3' AND ca.action_type IN ('DIVIDEND', 'JCP'))
              )
            ORDER BY ca.payment_date, ca.id
            """
        ).fetchall()

        for action in actions:
            if action["symbol"] == "OTEC":
                if action["currency"] != "NOK" or action["total_amount"] is None:
                    continue
                amount_original = -Decimal(action["total_amount"])
                amount_nok = amount_original
                fx_rate = Decimal("1")
                movement_type = "OTELLO_DISTRIBUTION"
                confidence = "CONFIRMED"
                description = "Otello cash distribution; confirmed total cash outflow."
            else:
                if action["currency"] != "BRL" or action["amount_per_share"] is None:
                    continue
                eligibility_date = action["ex_date"] or action["payment_date"]
                holding = _holding(connection, eligibility_date)
                fx = _nearest_fx(connection, "BRL", action["payment_date"])
                if holding is None or fx is None:
                    continue
                amount_original = Decimal(action["amount_per_share"]) * Decimal(holding["shares"])
                fx_rate = Decimal(fx["rate"])
                amount_nok = amount_original * fx_rate
                movement_type = "BEMOBI_JCP" if action["action_type"] == "JCP" else "BEMOBI_DIVIDEND"
                confidence = "ESTIMATED"
                description = (
                    f"Derived gross Bemobi {action['action_type']} receipt: "
                    f"{holding['shares']} shares x BRL {action['amount_per_share']} per share. "
                    "Net cash can differ due to withholding; anchor residual reconciles the difference."
                )

            existing = connection.execute(
                "SELECT id FROM cash_movements WHERE corporate_action_id = ?",
                (action["id"],),
            ).fetchone()
            values = (
                action["payment_date"],
                movement_type,
                decimal_text(amount_nok),
                decimal_text(amount_original),
                action["currency"],
                decimal_text(fx_rate),
                description,
                action["source_document_id"],
                confidence,
                action["id"],
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO cash_movements(
                        movement_date, movement_type, amount_nok, amount_original,
                        currency, fx_rate_to_nok, description, source_document_id,
                        confidence, corporate_action_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                written += 1
            else:
                connection.execute(
                    """
                    UPDATE cash_movements
                    SET movement_date = ?, movement_type = ?, amount_nok = ?,
                        amount_original = ?, currency = ?, fx_rate_to_nok = ?,
                        description = ?, source_document_id = ?, confidence = ?
                    WHERE corporate_action_id = ?
                    """,
                    values,
                )
                updated += 1
        connection.commit()
    return {"written": written, "updated": updated}


def _known_movements(connection, start_exclusive: str, end_inclusive: str) -> list[dict[str, Any]]:
    """Return model movements, conservatively excluding weekly buybacks that straddle an anchor.

    Weekly Otello status releases contain a total for a date range, not transaction-level
    daily cash. If that range starts on/before a reported cash anchor and ends after it,
    applying the full weekly amount after the anchor double-counts the pre-anchor portion.
    Until daily attachment rows are ingested, the whole weekly amount is therefore excluded
    from explicit post-anchor known flows and left to the anchored residual. The original
    confirmed amount remains in the returned audit payload.
    """
    result: list[dict[str, Any]] = []
    for row in connection.execute(
        """
        SELECT id, movement_date, movement_type, amount_nok, confidence,
               corporate_action_id, source_document_id, description
        FROM cash_movements
        WHERE movement_date > ? AND movement_date <= ?
        ORDER BY movement_date, id
        """,
        (start_exclusive, end_inclusive),
    ):
        item = dict(row)
        item["model_amount_nok"] = item["amount_nok"]
        item["timing_quality"] = "DIRECT_DATE"
        if item["movement_type"] == "OTELLO_BUYBACK":
            match = _BUYBACK_PERIOD_RE.search(item.get("description") or "")
            if match:
                period_start, period_end = match.groups()
                item["period_start"] = period_start
                item["period_end"] = period_end
                if period_start <= start_exclusive < item["movement_date"]:
                    item["model_amount_nok"] = "0"
                    item["timing_quality"] = "CROSS_ANCHOR_EXCLUDED"
                    item["model_note"] = (
                        "Confirmed weekly buyback total straddles the reported cash anchor; "
                        "excluded from explicit post-anchor flows to prevent double counting."
                    )
        result.append(item)
    return result


def _modeled_amount(item: dict[str, Any]) -> Decimal:
    return Decimal(item.get("model_amount_nok", item["amount_nok"]))


def rebuild_daily_cash(
    database_path: str | None = None,
    *,
    end_date: str | None = None,
) -> dict[str, Any]:
    sync_result = sync_corporate_action_cash_movements(database_path)
    cash_events_2022 = seed_2022_cash_events(database_path)
    with get_connection(database_path) as connection:
        anchors = _reported_anchors_nok(connection)
        if len(anchors) < 2:
            return {
                "written": 0,
                "periods": 0,
                "error": "Need at least two cash anchors",
                "sync_movements": sync_result,
                "cash_events_2022": cash_events_2022,
            }

        if end_date is None:
            row = connection.execute(
                "SELECT MAX(trading_date) AS max_date FROM market_prices"
            ).fetchone()
            end_date = row["max_date"] or anchors[-1]["date"]
        final_date = date.fromisoformat(end_date)

        connection.execute("DELETE FROM cash_period_calibrations")
        connection.execute("DELETE FROM cash_daily_estimates")
        written = 0
        high_residual_periods: list[dict[str, str]] = []
        cross_anchor_exclusions: list[dict[str, Any]] = []

        for start, end in zip(anchors, anchors[1:]):
            start_date = date.fromisoformat(start["date"])
            end_anchor_date = date.fromisoformat(end["date"])
            days = (end_anchor_date - start_date).days
            movements = _known_movements(connection, start["date"], end["date"])
            cross_anchor_exclusions.extend(
                {
                    "anchor_date": start["date"],
                    "movement_id": item["id"],
                    "movement_date": item["movement_date"],
                    "amount_nok": item["amount_nok"],
                    "period_start": item.get("period_start"),
                    "period_end": item.get("period_end"),
                }
                for item in movements
                if item.get("timing_quality") == "CROSS_ANCHOR_EXCLUDED"
            )
            known_total = sum((_modeled_amount(item) for item in movements), Decimal("0"))
            residual = end["cash_nok"] - start["cash_nok"] - known_total
            residual_per_day = residual / Decimal(days)
            residual_ratio = (
                abs(residual) / abs(start["cash_nok"]) if start["cash_nok"] != 0 else Decimal("0")
            )
            quality = "HIGH_RESIDUAL" if residual_ratio > Decimal("0.25") else "ANCHORED"
            if quality == "HIGH_RESIDUAL":
                high_residual_periods.append(
                    {"start": start["date"], "end": end["date"], "residual_nok": decimal_text(residual)}
                )

            inputs = {
                "start_anchor": start,
                "end_anchor": end,
                "movements": movements,
                "method": "linear-residual-between-reported-anchors-v2-cross-anchor-safe",
            }
            inputs_hash = _canonical_hash(inputs)
            connection.execute(
                """
                INSERT INTO cash_period_calibrations(
                    start_anchor_date, end_anchor_date, start_cash_nok, end_cash_nok,
                    known_movements_nok, residual_nok, residual_per_day_nok,
                    calendar_days, inputs_hash, quality, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    start["date"], end["date"], decimal_text(start["cash_nok"]),
                    decimal_text(end["cash_nok"]), decimal_text(known_total),
                    decimal_text(residual), decimal_text(residual_per_day), days,
                    inputs_hash, quality,
                    "Residual includes unmodelled operating cash flow, taxes, FX/revaluation and other cash movements. Weekly buyback totals that straddle the start anchor are excluded from explicit known flows to prevent pre-anchor double counting.",
                ),
            )

            movements_by_date: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            for item in movements:
                movements_by_date[item["movement_date"]] += _modeled_amount(item)
            cumulative_known = Decimal("0")
            for offset in range(days + 1):
                current = start_date + timedelta(days=offset)
                current_text = current.isoformat()
                if offset > 0:
                    cumulative_known += movements_by_date[current_text]
                cumulative_residual = residual_per_day * Decimal(offset)
                cash_nok = start["cash_nok"] + cumulative_known + cumulative_residual
                day_quality = "REPORTED" if offset in (0, days) else "ANCHORED_ESTIMATE"
                day_inputs = {
                    "period_hash": inputs_hash,
                    "date": current_text,
                    "offset": offset,
                    "known": decimal_text(cumulative_known),
                    "residual": decimal_text(cumulative_residual),
                }
                connection.execute(
                    """
                    INSERT INTO cash_daily_estimates(
                        estimate_date, cash_nok, period_start_date, period_end_date,
                        cumulative_known_movements_nok, cumulative_residual_nok,
                        quality, inputs_hash, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(estimate_date) DO UPDATE SET
                        cash_nok = excluded.cash_nok,
                        period_start_date = excluded.period_start_date,
                        period_end_date = excluded.period_end_date,
                        cumulative_known_movements_nok = excluded.cumulative_known_movements_nok,
                        cumulative_residual_nok = excluded.cumulative_residual_nok,
                        quality = excluded.quality,
                        inputs_hash = excluded.inputs_hash,
                        notes = excluded.notes
                    """,
                    (
                        current_text, decimal_text(cash_nok), start["date"], end["date"],
                        decimal_text(cumulative_known), decimal_text(cumulative_residual),
                        day_quality, _canonical_hash(day_inputs),
                        "Reported anchor" if day_quality == "REPORTED" else "Anchored estimate; reconciles exactly to both surrounding reported cash anchors.",
                    ),
                )
                written += 1

        latest = anchors[-1]
        latest_date = date.fromisoformat(latest["date"])
        if final_date > latest_date:
            movements = _known_movements(connection, latest["date"], final_date.isoformat())
            cross_anchor_exclusions.extend(
                {
                    "anchor_date": latest["date"],
                    "movement_id": item["id"],
                    "movement_date": item["movement_date"],
                    "amount_nok": item["amount_nok"],
                    "period_start": item.get("period_start"),
                    "period_end": item.get("period_end"),
                }
                for item in movements
                if item.get("timing_quality") == "CROSS_ANCHOR_EXCLUDED"
            )
            by_date: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            for item in movements:
                by_date[item["movement_date"]] += _modeled_amount(item)
            cumulative = Decimal("0")
            for offset in range(1, (final_date - latest_date).days + 1):
                current = latest_date + timedelta(days=offset)
                current_text = current.isoformat()
                cumulative += by_date[current_text]
                cash_nok = latest["cash_nok"] + cumulative
                payload = {
                    "last_reported_anchor": latest,
                    "date": current_text,
                    "known_movements_nok": decimal_text(cumulative),
                    "method": "known-flows-only-forecast-v2-cross-anchor-safe",
                }
                connection.execute(
                    """
                    INSERT INTO cash_daily_estimates(
                        estimate_date, cash_nok, period_start_date, period_end_date,
                        cumulative_known_movements_nok, cumulative_residual_nok,
                        quality, inputs_hash, notes
                    ) VALUES (?, ?, ?, NULL, ?, '0', 'FORECAST_PARTIAL', ?, ?)
                    ON CONFLICT(estimate_date) DO UPDATE SET
                        cash_nok = excluded.cash_nok,
                        period_start_date = excluded.period_start_date,
                        period_end_date = NULL,
                        cumulative_known_movements_nok = excluded.cumulative_known_movements_nok,
                        cumulative_residual_nok = '0',
                        quality = excluded.quality,
                        inputs_hash = excluded.inputs_hash,
                        notes = excluded.notes
                    """,
                    (
                        current_text, decimal_text(cash_nok), latest["date"],
                        decimal_text(cumulative), _canonical_hash(payload),
                        "Partial forecast from last reported cash anchor using known corporate-action flows only. Weekly buybacks that straddle the anchor are excluded rather than double-counted; operating costs and unseeded flows are not accrued.",
                    ),
                )
                written += 1

        connection.commit()

    return {
        "written": written,
        "periods": len(anchors) - 1,
        "from": anchors[0]["date"],
        "to": end_date,
        "last_reported_anchor": anchors[-1]["date"],
        "sync_movements": sync_result,
        "cash_events_2022": cash_events_2022,
        "high_residual_periods": high_residual_periods,
        "cross_anchor_buybacks_excluded": cross_anchor_exclusions,
    }


def daily_cash_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        aggregate = connection.execute(
            """
            SELECT COUNT(*) AS n, MIN(estimate_date) AS min_date, MAX(estimate_date) AS max_date,
                   SUM(CASE WHEN quality = 'REPORTED' THEN 1 ELSE 0 END) AS reported,
                   SUM(CASE WHEN quality = 'FORECAST_PARTIAL' THEN 1 ELSE 0 END) AS forecast
            FROM cash_daily_estimates
            """
        ).fetchone()
        periods = connection.execute(
            """
            SELECT COUNT(*) AS n,
                   SUM(CASE WHEN quality = 'HIGH_RESIDUAL' THEN 1 ELSE 0 END) AS high_residual
            FROM cash_period_calibrations
            """
        ).fetchone()
        latest = connection.execute(
            """
            SELECT estimate_date, cash_nok, quality, notes
            FROM cash_daily_estimates ORDER BY estimate_date DESC LIMIT 1
            """
        ).fetchone()
        return {
            "status": "ok" if aggregate["n"] else "empty",
            "count": aggregate["n"],
            "from": aggregate["min_date"],
            "to": aggregate["max_date"],
            "reported_days": aggregate["reported"],
            "forecast_days": aggregate["forecast"],
            "periods": periods["n"],
            "high_residual_periods": periods["high_residual"],
            "latest": dict(latest) if latest is not None else None,
        }

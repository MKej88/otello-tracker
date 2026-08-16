from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text

MAX_FX_LOOKBACK_DAYS = 7


def _hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _nearest_usd_nok(connection, day: str):
    floor = (date.fromisoformat(day) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT id, substr(observed_at, 1, 10) AS rate_date, rate
        FROM fx_rates
        WHERE base_currency = 'USD' AND quote_currency = 'NOK'
          AND substr(observed_at, 1, 10) <= ?
          AND substr(observed_at, 1, 10) >= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1
        """,
        (day, floor),
    ).fetchone()


def rebuild_other_net_assets_anchors(database_path: str | None = None) -> dict[str, Any]:
    written = 0
    skipped: list[dict[str, str]] = []
    with get_connection(database_path) as connection:
        anchors = connection.execute(
            """
            SELECT id, as_of_date, other_net_assets_reported, reported_currency,
                   precision_status, source_document_id, restated, notes
            FROM other_net_assets_reported_anchors
            ORDER BY as_of_date
            """
        ).fetchall()
        for anchor in anchors:
            if anchor["reported_currency"] != "USD":
                skipped.append({"date": anchor["as_of_date"], "reason": "unsupported currency"})
                continue
            fx = _nearest_usd_nok(connection, anchor["as_of_date"])
            if fx is None:
                skipped.append({"date": anchor["as_of_date"], "reason": "missing USD/NOK"})
                continue

            amount_usd = Decimal(anchor["other_net_assets_reported"])
            usd_nok = Decimal(fx["rate"])
            amount_nok = amount_usd * usd_nok
            quality = "ROUNDED_REPORTED" if anchor["precision_status"] == "ROUNDED_0_1M" else "REPORTED"
            payload = {
                "reported_anchor_id": anchor["id"],
                "amount_usd": decimal_text(amount_usd),
                "usd_nok_rate": decimal_text(usd_nok),
                "fx_rate_id": fx["id"],
                "fx_rate_date": fx["rate_date"],
                "restated": bool(anchor["restated"]),
            }
            existing = connection.execute(
                "SELECT id FROM other_net_assets_anchors WHERE reported_anchor_id = ?",
                (anchor["id"],),
            ).fetchone()
            description = "Reported other net assets excluding cash and Bemobi carrying value"
            notes = (
                f"USD/NOK {decimal_text(usd_nok)} from {fx['rate_date']}; "
                f"reported quality {anchor['precision_status']}; "
                f"restated={bool(anchor['restated'])}. {anchor['notes'] or ''}"
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO other_net_assets_anchors(
                        as_of_date, amount_nok, description, source_document_id, notes,
                        reported_anchor_id, amount_usd, fx_rate_to_nok, quality, inputs_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        anchor["as_of_date"], decimal_text(amount_nok), description,
                        anchor["source_document_id"], notes, anchor["id"],
                        decimal_text(amount_usd), decimal_text(usd_nok), quality, _hash(payload),
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE other_net_assets_anchors
                    SET as_of_date = ?, amount_nok = ?, description = ?,
                        source_document_id = ?, notes = ?, amount_usd = ?,
                        fx_rate_to_nok = ?, quality = ?, inputs_hash = ?
                    WHERE id = ?
                    """,
                    (
                        anchor["as_of_date"], decimal_text(amount_nok), description,
                        anchor["source_document_id"], notes, decimal_text(amount_usd),
                        decimal_text(usd_nok), quality, _hash(payload), existing["id"],
                    ),
                )
            written += 1
        connection.commit()
    return {"written": written, "skipped": skipped}


def rebuild_daily_other_net_assets(
    database_path: str | None = None,
    *,
    end_date: str | None = None,
) -> dict[str, Any]:
    written = 0
    skipped_fx = 0
    with get_connection(database_path) as connection:
        anchors = connection.execute(
            """
            SELECT r.id, r.as_of_date, r.other_net_assets_reported
            FROM other_net_assets_reported_anchors r
            JOIN other_net_assets_anchors n ON n.reported_anchor_id = r.id
            ORDER BY r.as_of_date
            """
        ).fetchall()
        if not anchors:
            return {"written": 0, "error": "no normalized other-net-assets anchors"}

        start = date.fromisoformat(anchors[0]["as_of_date"])
        if end_date is None:
            row = connection.execute(
                "SELECT MAX(estimate_date) AS d FROM cash_daily_estimates"
            ).fetchone()
            end = date.fromisoformat(row["d"]) if row is not None and row["d"] else date.fromisoformat(anchors[-1]["as_of_date"])
        else:
            end = date.fromisoformat(end_date)
        if end < start:
            return {"written": 0, "from": start.isoformat(), "to": end.isoformat()}

        anchor_dates = [date.fromisoformat(row["as_of_date"]) for row in anchors]
        current = start
        while current <= end:
            current_iso = current.isoformat()
            previous_index = max(i for i, d in enumerate(anchor_dates) if d <= current)
            start_anchor = anchors[previous_index]
            start_day = anchor_dates[previous_index]
            start_value = Decimal(start_anchor["other_net_assets_reported"])

            if current == start_day:
                end_anchor = start_anchor
                amount_usd = start_value
                quality = "REPORTED_ANCHOR"
            elif previous_index + 1 < len(anchors):
                end_anchor = anchors[previous_index + 1]
                end_day = anchor_dates[previous_index + 1]
                end_value = Decimal(end_anchor["other_net_assets_reported"])
                elapsed = Decimal((current - start_day).days)
                span = Decimal((end_day - start_day).days)
                amount_usd = start_value + (end_value - start_value) * elapsed / span
                quality = "INTERPOLATED"
            else:
                end_anchor = None
                amount_usd = start_value
                quality = "FORECAST_PARTIAL"

            fx = _nearest_usd_nok(connection, current_iso)
            if fx is None:
                skipped_fx += 1
                current += timedelta(days=1)
                continue
            usd_nok = Decimal(fx["rate"])
            amount_nok = amount_usd * usd_nok
            payload = {
                "date": current_iso,
                "amount_usd": decimal_text(amount_usd),
                "usd_nok": decimal_text(usd_nok),
                "fx_rate_id": fx["id"],
                "start_anchor_id": start_anchor["id"],
                "end_anchor_id": end_anchor["id"] if end_anchor is not None else None,
                "quality": quality,
            }
            notes = (
                "Report-date ONA converted with daily USD/NOK."
                if quality == "REPORTED_ANCHOR"
                else "ONA linearly interpolated in USD between report anchors, then converted at daily USD/NOK."
                if quality == "INTERPOLATED"
                else "Latest reported ONA carried forward in USD after the last report anchor; awaiting next report."
            )
            connection.execute(
                """
                INSERT INTO other_net_assets_daily_estimates(
                    estimate_date, amount_usd, usd_nok_rate, amount_nok, quality,
                    start_anchor_id, end_anchor_id, inputs_hash, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(estimate_date) DO UPDATE SET
                    amount_usd = excluded.amount_usd,
                    usd_nok_rate = excluded.usd_nok_rate,
                    amount_nok = excluded.amount_nok,
                    quality = excluded.quality,
                    start_anchor_id = excluded.start_anchor_id,
                    end_anchor_id = excluded.end_anchor_id,
                    inputs_hash = excluded.inputs_hash,
                    notes = excluded.notes,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (
                    current_iso, decimal_text(amount_usd), decimal_text(usd_nok),
                    decimal_text(amount_nok), quality, start_anchor["id"],
                    end_anchor["id"] if end_anchor is not None else None,
                    _hash(payload), notes,
                ),
            )
            written += 1
            current += timedelta(days=1)
        connection.commit()

    return {
        "written": written,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "skipped_missing_fx": skipped_fx,
    }


def other_net_assets_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        reported = connection.execute(
            "SELECT COUNT(*) n, MIN(as_of_date) min_date, MAX(as_of_date) max_date FROM other_net_assets_reported_anchors"
        ).fetchone()
        daily = connection.execute(
            """
            SELECT COUNT(*) n, MIN(estimate_date) min_date, MAX(estimate_date) max_date,
                   SUM(CASE WHEN quality = 'FORECAST_PARTIAL' THEN 1 ELSE 0 END) forecast_partial
            FROM other_net_assets_daily_estimates
            """
        ).fetchone()
        latest = connection.execute(
            """
            SELECT estimate_date, amount_usd, usd_nok_rate, amount_nok, quality, notes
            FROM other_net_assets_daily_estimates ORDER BY estimate_date DESC LIMIT 1
            """
        ).fetchone()
        return {
            "status": "ok" if daily["n"] else "empty",
            "reported_anchors": {"count": reported["n"], "from": reported["min_date"], "to": reported["max_date"]},
            "daily": {"count": daily["n"], "from": daily["min_date"], "to": daily["max_date"], "forecast_partial": daily["forecast_partial"]},
            "latest": dict(latest) if latest is not None else None,
        }

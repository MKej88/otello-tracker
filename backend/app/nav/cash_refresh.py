from __future__ import annotations

import hashlib
import json
from typing import Any

from app.db.connection import get_connection
from app.db.runtime_state import get_runtime_state, set_runtime_state
from app.nav.cash_curve import rebuild_daily_cash

_STATE_KEY = "cash_curve_input_signature_v1"


def _rows(connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def cash_input_signature(database_path: str | None, *, end_date: str) -> str:
    """Hash cash-model inputs, not generated daily rows.

    The signature is deliberately conservative. It includes all explicit cash movements,
    report anchors, corporate actions and holdings plus a compact FX freshness aggregate.
    A daily ECB refresh can therefore trigger one cash rebuild, while unchanged 30-minute
    fast cycles avoid deleting/recreating the full cash history.
    """
    with get_connection(database_path) as connection:
        payload = {
            "end_date": end_date,
            "anchors": _rows(
                connection,
                """
                SELECT id, as_of_date, reported_amount, reported_currency,
                       anchor_type, source_document_id, notes
                FROM cash_anchors
                ORDER BY id
                """,
            ),
            "movements": _rows(
                connection,
                """
                SELECT id, movement_date, movement_type, amount_nok, amount_original,
                       currency, fx_rate_to_nok, source_document_id, confidence,
                       corporate_action_id, description
                FROM cash_movements
                WHERE movement_date <= ?
                ORDER BY id
                """,
                (end_date,),
            ),
            "corporate_actions": _rows(
                connection,
                """
                SELECT id, issuer_instrument_id, action_type, announcement_date,
                       ex_date, record_date, payment_date, amount_per_share,
                       total_amount, currency, source_document_id, quantity,
                       component_group
                FROM corporate_actions
                WHERE COALESCE(payment_date, announcement_date, ex_date, record_date, '') <= ?
                ORDER BY id
                """,
                (end_date,),
            ),
            "holdings": _rows(
                connection,
                """
                SELECT id, effective_from, effective_to, shares, ownership_pct,
                       source_document_id
                FROM bemobi_holdings
                WHERE effective_from <= ?
                ORDER BY id
                """,
                (end_date,),
            ),
            "fx": _rows(
                connection,
                """
                SELECT base_currency, quote_currency, COUNT(*) AS n,
                       MAX(id) AS max_id, MAX(fetched_at) AS max_fetched_at,
                       MAX(observed_at) AS max_observed_at
                FROM fx_rates
                WHERE quote_currency='NOK' AND base_currency IN ('BRL','USD')
                  AND substr(observed_at,1,10) <= ?
                GROUP BY base_currency, quote_currency
                ORDER BY base_currency, quote_currency
                """,
                (end_date,),
            ),
        }
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rebuild_daily_cash_if_changed(
    database_path: str | None = None,
    *,
    end_date: str,
    force: bool = False,
) -> dict[str, Any]:
    before = cash_input_signature(database_path, end_date=end_date)
    previous = get_runtime_state(_STATE_KEY, database_path)
    with get_connection(database_path) as connection:
        row = connection.execute(
            "SELECT MAX(estimate_date) AS max_date FROM cash_daily_estimates"
        ).fetchone()
        existing_to = row["max_date"] if row is not None else None

    if not force and previous == before and existing_to is not None and existing_to >= end_date:
        return {
            "skipped": True,
            "reason": "cash_inputs_unchanged",
            "to": existing_to,
            "input_signature": before,
        }

    result = rebuild_daily_cash(database_path, end_date=end_date)
    after = cash_input_signature(database_path, end_date=end_date)
    set_runtime_state(_STATE_KEY, after, database_path)
    result["skipped"] = False
    result["forced"] = force
    result["input_signature"] = after
    return result

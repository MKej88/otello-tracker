from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from repository import D1WriteRepository

MAX_LOOKBACK_DAYS = 7
CASH_STATE_KEY = "cash_curve_input_signature_v1"
BUYBACK_PERIOD_RE = re.compile(
    r"during\s+(20\d{2}-\d{2}-\d{2})[–-](20\d{2}-\d{2}-\d{2})",
    re.I,
)


def decimal_text(value: Decimal | str | int | float) -> str:
    return format(Decimal(str(value)), "f")


def stable_hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def nearest_fx(
    repository: D1WriteRepository,
    base_currency: str,
    as_of_date: str,
) -> dict[str, Any] | None:
    floor = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT id, substr(observed_at,1,10) AS rate_date, rate, quality
        FROM fx_rates
        WHERE base_currency=? AND quote_currency='NOK'
          AND substr(observed_at,1,10)<=?
          AND substr(observed_at,1,10)>=?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (base_currency, as_of_date, floor),
    )


async def _reported_anchors(repository: D1WriteRepository) -> list[dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT id, as_of_date, reported_amount, reported_currency,
               source_document_id, notes
        FROM cash_anchors
        WHERE anchor_type='REPORTED'
        ORDER BY as_of_date, id
        """
    )
    anchors: list[dict[str, Any]] = []
    for row in rows:
        currency = str(row["reported_currency"])
        reported_amount = Decimal(str(row["reported_amount"]))
        if currency == "NOK":
            rate = Decimal("1")
            fx_id = None
            fx_date = str(row["as_of_date"])
        else:
            fx = await nearest_fx(repository, currency, str(row["as_of_date"]))
            if fx is None:
                continue
            rate = Decimal(str(fx["rate"]))
            fx_id = int(fx["id"])
            fx_date = str(fx["rate_date"])
        anchors.append(
            {
                "id": int(row["id"]),
                "date": str(row["as_of_date"]),
                "cash_nok": reported_amount * rate,
                "reported_amount": decimal_text(reported_amount),
                "reported_currency": currency,
                "fx_rate_to_nok": decimal_text(rate),
                "fx_rate_id": fx_id,
                "fx_rate_date": fx_date,
                "source_document_id": int(row["source_document_id"]),
            }
        )
    return anchors


async def _known_movements(
    repository: D1WriteRepository,
    start_exclusive: str,
    end_inclusive: str,
) -> list[dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT id, movement_date, movement_type, amount_nok, confidence,
               corporate_action_id, source_document_id, description
        FROM cash_movements
        WHERE movement_date>? AND movement_date<=?
        ORDER BY movement_date, id
        """,
        (start_exclusive, end_inclusive),
    )
    result: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        item["model_amount_nok"] = item["amount_nok"]
        item["timing_quality"] = "DIRECT_DATE"
        if item["movement_type"] == "OTELLO_BUYBACK":
            match = BUYBACK_PERIOD_RE.search(str(item.get("description") or ""))
            if match:
                period_start, period_end = match.groups()
                item["period_start"] = period_start
                item["period_end"] = period_end
                if period_start <= start_exclusive < str(item["movement_date"]):
                    item["model_amount_nok"] = "0"
                    item["timing_quality"] = "CROSS_ANCHOR_EXCLUDED"
                    item["model_note"] = (
                        "Confirmed weekly buyback total straddles the reported cash anchor; "
                        "excluded from explicit post-anchor flows to prevent double counting."
                    )
        result.append(item)
    return result


def _model_amount(item: dict[str, Any]) -> Decimal:
    return Decimal(str(item.get("model_amount_nok", item["amount_nok"])))


async def cash_input_signature(
    repository: D1WriteRepository,
    *,
    end_date: str,
) -> str:
    payload = {
        "end_date": end_date,
        "anchors": await repository.all(
            """
            SELECT id, as_of_date, reported_amount, reported_currency,
                   anchor_type, source_document_id, notes
            FROM cash_anchors ORDER BY id
            """
        ),
        "movements": await repository.all(
            """
            SELECT id, movement_date, movement_type, amount_nok, amount_original,
                   currency, fx_rate_to_nok, source_document_id, confidence,
                   corporate_action_id, description
            FROM cash_movements
            WHERE movement_date<=?
            ORDER BY id
            """,
            (end_date,),
        ),
        "corporate_actions": await repository.all(
            """
            SELECT id, issuer_instrument_id, action_type, announcement_date,
                   ex_date, record_date, payment_date, amount_per_share,
                   total_amount, currency, source_document_id, quantity,
                   component_group
            FROM corporate_actions
            WHERE COALESCE(payment_date,announcement_date,ex_date,record_date,'')<=?
            ORDER BY id
            """,
            (end_date,),
        ),
        "holdings": await repository.all(
            """
            SELECT id, effective_from, effective_to, shares, ownership_pct,
                   source_document_id
            FROM bemobi_holdings
            WHERE effective_from<=?
            ORDER BY id
            """,
            (end_date,),
        ),
        "fx": await repository.all(
            """
            SELECT base_currency, quote_currency, COUNT(*) AS n,
                   MAX(id) AS max_id, MAX(fetched_at) AS max_fetched_at,
                   MAX(observed_at) AS max_observed_at
            FROM fx_rates
            WHERE quote_currency='NOK' AND base_currency IN ('BRL','USD')
              AND substr(observed_at,1,10)<=?
            GROUP BY base_currency, quote_currency
            ORDER BY base_currency, quote_currency
            """,
            (end_date,),
        ),
    }
    return stable_hash(payload)


async def _runtime_state(repository: D1WriteRepository, key: str) -> str | None:
    row = await repository.first("SELECT value FROM runtime_state WHERE key=?", (key,))
    return str(row["value"]) if row is not None else None


async def _set_runtime_state(repository: D1WriteRepository, key: str, value: str) -> None:
    await repository.run(
        """
        INSERT INTO runtime_state(key,value) VALUES (?,?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (key, value),
    )


async def rebuild_daily_cash_if_changed(
    repository: D1WriteRepository,
    *,
    end_date: str,
    force: bool = False,
) -> dict[str, Any]:
    signature_before = await cash_input_signature(repository, end_date=end_date)
    previous = await _runtime_state(repository, CASH_STATE_KEY)
    current = await repository.first("SELECT MAX(estimate_date) AS d FROM cash_daily_estimates")
    current_to = str(current["d"]) if current and current.get("d") else None
    if not force and previous == signature_before and current_to is not None and current_to >= end_date:
        return {
            "skipped": True,
            "reason": "cash_inputs_unchanged",
            "to": current_to,
            "input_signature": signature_before,
            "written": 0,
        }

    anchors = await _reported_anchors(repository)
    if len(anchors) < 2:
        raise ValueError("Kontantkurven krever minst to rapporterte ankere med tilgjengelig FX")

    final_day = date.fromisoformat(end_date)
    first_anchor_date = str(anchors[0]["date"])
    expected_periods: list[tuple[str, str]] = []
    high_residual_periods: list[dict[str, str]] = []
    cross_anchor_exclusions: list[dict[str, Any]] = []
    written = 0

    for start, end in zip(anchors, anchors[1:]):
        start_day = date.fromisoformat(start["date"])
        end_day = date.fromisoformat(end["date"])
        days = (end_day - start_day).days
        if days <= 0:
            continue
        movements = await _known_movements(repository, start["date"], end["date"])
        cross_anchor_exclusions.extend(
            {
                "movement_id": int(item["id"]),
                "movement_date": item["movement_date"],
                "period_start": item.get("period_start"),
                "period_end": item.get("period_end"),
            }
            for item in movements
            if item.get("timing_quality") == "CROSS_ANCHOR_EXCLUDED"
        )
        known_total = sum((_model_amount(item) for item in movements), Decimal("0"))
        residual = end["cash_nok"] - start["cash_nok"] - known_total
        residual_per_day = residual / Decimal(days)
        residual_ratio = (
            abs(residual) / abs(start["cash_nok"])
            if start["cash_nok"] != 0
            else Decimal("0")
        )
        quality = "HIGH_RESIDUAL" if residual_ratio > Decimal("0.25") else "ANCHORED"
        if quality == "HIGH_RESIDUAL":
            high_residual_periods.append(
                {
                    "start": start["date"],
                    "end": end["date"],
                    "residual_nok": decimal_text(residual),
                }
            )
        period_inputs = {
            "start_anchor": start,
            "end_anchor": end,
            "movements": movements,
            "method": "linear-residual-between-reported-anchors-v2-cross-anchor-safe",
        }
        period_hash = stable_hash(period_inputs)
        expected_periods.append((start["date"], end["date"]))
        await repository.run(
            """
            INSERT INTO cash_period_calibrations(
                start_anchor_date,end_anchor_date,start_cash_nok,end_cash_nok,
                known_movements_nok,residual_nok,residual_per_day_nok,
                calendar_days,inputs_hash,quality,notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(start_anchor_date,end_anchor_date) DO UPDATE SET
                start_cash_nok=excluded.start_cash_nok,
                end_cash_nok=excluded.end_cash_nok,
                known_movements_nok=excluded.known_movements_nok,
                residual_nok=excluded.residual_nok,
                residual_per_day_nok=excluded.residual_per_day_nok,
                calendar_days=excluded.calendar_days,
                inputs_hash=excluded.inputs_hash,
                quality=excluded.quality,
                notes=excluded.notes
            """,
            (
                start["date"], end["date"], decimal_text(start["cash_nok"]),
                decimal_text(end["cash_nok"]), decimal_text(known_total),
                decimal_text(residual), decimal_text(residual_per_day), days,
                period_hash, quality,
                "Known cash movements plus linear residual calibrated exactly to reported anchors.",
            ),
        )

        daily_movements: dict[str, Decimal] = {}
        for movement in movements:
            movement_date = str(movement["movement_date"])
            daily_movements[movement_date] = (
                daily_movements.get(movement_date, Decimal("0")) + _model_amount(movement)
            )
        cumulative_known = Decimal("0")
        for offset in range(days + 1):
            current_day = start_day + timedelta(days=offset)
            if current_day > final_day:
                break
            current_iso = current_day.isoformat()
            if offset > 0:
                cumulative_known += daily_movements.get(current_iso, Decimal("0"))
            cumulative_residual = residual_per_day * Decimal(offset)
            cash_nok = start["cash_nok"] + cumulative_known + cumulative_residual
            day_quality = "REPORTED" if offset in (0, days) else "ANCHORED_ESTIMATE"
            inputs_hash = stable_hash(
                {
                    "period_hash": period_hash,
                    "date": current_iso,
                    "known": decimal_text(cumulative_known),
                    "residual": decimal_text(cumulative_residual),
                }
            )
            await repository.run(
                """
                INSERT INTO cash_daily_estimates(
                    estimate_date,cash_nok,period_start_date,period_end_date,
                    cumulative_known_movements_nok,cumulative_residual_nok,
                    quality,inputs_hash,notes
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(estimate_date) DO UPDATE SET
                    cash_nok=excluded.cash_nok,
                    period_start_date=excluded.period_start_date,
                    period_end_date=excluded.period_end_date,
                    cumulative_known_movements_nok=excluded.cumulative_known_movements_nok,
                    cumulative_residual_nok=excluded.cumulative_residual_nok,
                    quality=excluded.quality,
                    inputs_hash=excluded.inputs_hash,
                    notes=excluded.notes
                """,
                (
                    current_iso, decimal_text(cash_nok), start["date"], end["date"],
                    decimal_text(cumulative_known), decimal_text(cumulative_residual),
                    day_quality, inputs_hash,
                    "Reported anchor / calibrated estimate using known movements and linear residual.",
                ),
            )
            written += 1

    last_anchor = anchors[-1]
    last_anchor_day = date.fromisoformat(last_anchor["date"])
    if final_day > last_anchor_day:
        movements = await _known_movements(repository, last_anchor["date"], end_date)
        daily_movements: dict[str, Decimal] = {}
        for movement in movements:
            movement_date = str(movement["movement_date"])
            daily_movements[movement_date] = (
                daily_movements.get(movement_date, Decimal("0")) + _model_amount(movement)
            )
        cumulative_known = Decimal("0")
        for offset in range((final_day - last_anchor_day).days + 1):
            current_day = last_anchor_day + timedelta(days=offset)
            current_iso = current_day.isoformat()
            if offset > 0:
                cumulative_known += daily_movements.get(current_iso, Decimal("0"))
            cash_nok = last_anchor["cash_nok"] + cumulative_known
            day_quality = "REPORTED" if offset == 0 else "FORECAST_PARTIAL"
            inputs_hash = stable_hash(
                {
                    "last_reported_anchor": last_anchor,
                    "date": current_iso,
                    "known_movements_nok": decimal_text(cumulative_known),
                    "method": "known-flows-only-forecast-v2-cross-anchor-safe",
                }
            )
            await repository.run(
                """
                INSERT INTO cash_daily_estimates(
                    estimate_date,cash_nok,period_start_date,period_end_date,
                    cumulative_known_movements_nok,cumulative_residual_nok,
                    quality,inputs_hash,notes
                ) VALUES (?,?,?,NULL,?,'0',?,?,?)
                ON CONFLICT(estimate_date) DO UPDATE SET
                    cash_nok=excluded.cash_nok,
                    period_start_date=excluded.period_start_date,
                    period_end_date=NULL,
                    cumulative_known_movements_nok=excluded.cumulative_known_movements_nok,
                    cumulative_residual_nok='0',
                    quality=excluded.quality,
                    inputs_hash=excluded.inputs_hash,
                    notes=excluded.notes
                """,
                (
                    current_iso, decimal_text(cash_nok), last_anchor["date"],
                    decimal_text(cumulative_known), day_quality, inputs_hash,
                    "Known flows only after latest reported cash anchor; no unreported OPEX/tax forecast.",
                ),
            )
            written += 1

    # The generated cash curve is contiguous from the first reported anchor through end_date.
    # Clean by two date bounds instead of thousands of D1 bind parameters.
    await repository.run(
        "DELETE FROM cash_daily_estimates WHERE estimate_date<? OR estimate_date>?",
        (first_anchor_date, end_date),
    )

    # Anchor periods are few. Remove obsolete calibrations one row at a time to avoid a
    # dynamic wide predicate in D1.
    existing_periods = await repository.all(
        "SELECT id,start_anchor_date,end_anchor_date FROM cash_period_calibrations ORDER BY id"
    )
    expected = set(expected_periods)
    for row in existing_periods:
        if (str(row["start_anchor_date"]), str(row["end_anchor_date"])) not in expected:
            await repository.run(
                "DELETE FROM cash_period_calibrations WHERE id=?",
                (int(row["id"]),),
            )

    signature_after = await cash_input_signature(repository, end_date=end_date)
    await _set_runtime_state(repository, CASH_STATE_KEY, signature_after)
    return {
        "written": written,
        "to": end_date,
        "skipped": False,
        "forced": force,
        "input_signature": signature_after,
        "high_residual_periods": high_residual_periods,
        "cross_anchor_exclusions": cross_anchor_exclusions,
    }

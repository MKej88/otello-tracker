from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text
from app.history.distributions import seed_bemobi_distributions
from app.nav.option_liability import load_option_program, option_liability_for_day

MAX_FX_LOOKBACK_DAYS = 7


def _hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _nearest_fx(connection, base: str, day: str):
    floor = (date.fromisoformat(day) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT fr.id, substr(fr.observed_at, 1, 10) AS rate_date, fr.rate,
               s.code AS source_code
        FROM fx_rates fr
        JOIN sources s ON s.id = fr.source_id
        WHERE fr.base_currency = ? AND fr.quote_currency = 'NOK'
          AND substr(fr.observed_at, 1, 10) <= ?
          AND substr(fr.observed_at, 1, 10) >= ?
        ORDER BY substr(fr.observed_at, 1, 10) DESC,
                 CASE s.code
                   WHEN 'NORGES_BANK' THEN 0
                   WHEN 'ECB' THEN 1
                   ELSE 5
                 END,
                 fr.observed_at DESC,
                 fr.id DESC
        LIMIT 1
        """,
        (base, day, floor),
    ).fetchone()


def _nearest_usd_nok(connection, day: str):
    return _nearest_fx(connection, "USD", day)


def _holding(connection, day: str):
    return connection.execute(
        """
        SELECT id, shares, effective_from, effective_to
        FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (day, day),
    ).fetchone()


def rebuild_other_net_assets_anchors(database_path: str | None = None) -> dict[str, Any]:
    written = 0
    skipped: list[dict[str, str]] = []
    with get_connection(database_path) as connection:
        anchors = connection.execute(
            """
            SELECT id, as_of_date, other_net_assets_reported, reported_currency,
                   precision_status, source_document_id, restated, notes,
                   associated_receivable_reported, base_other_net_assets_reported,
                   option_liability_reported, base_other_net_assets_ex_option_reported
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
                "associated_receivable_usd": anchor["associated_receivable_reported"],
                "base_other_net_assets_usd": anchor["base_other_net_assets_reported"],
                "option_liability_usd": anchor["option_liability_reported"],
                "base_ex_option_usd": anchor["base_other_net_assets_ex_option_reported"],
                "usd_nok_rate": decimal_text(usd_nok),
                "fx_rate_id": fx["id"],
                "fx_rate_date": fx["rate_date"],
                "restated": bool(anchor["restated"]),
            }
            existing = connection.execute(
                "SELECT id FROM other_net_assets_anchors WHERE reported_anchor_id = ?",
                (anchor["id"],),
            ).fetchone()
            description = (
                "Reported ONA excluding cash and Bemobi carrying value; Bemobi receivables and "
                "cash-settled Otello option liability are decomposed for daily valuation"
            )
            notes = (
                f"USD/NOK {decimal_text(usd_nok)} from {fx['rate_date']}; "
                f"reported quality {anchor['precision_status']}; restated={bool(anchor['restated'])}; "
                f"associated receivable USD {anchor['associated_receivable_reported']}; "
                f"option liability USD {anchor['option_liability_reported']}; "
                f"base ex option USD {anchor['base_other_net_assets_ex_option_reported']}. "
                f"{anchor['notes'] or ''}"
            )
            values = (
                anchor["as_of_date"], decimal_text(amount_nok), description,
                anchor["source_document_id"], notes, decimal_text(amount_usd),
                decimal_text(usd_nok), quality, _hash(payload),
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO other_net_assets_anchors(
                        as_of_date, amount_nok, description, source_document_id, notes,
                        reported_anchor_id, amount_usd, fx_rate_to_nok, quality, inputs_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*values[:5], anchor["id"], *values[5:]),
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
                    (*values, existing["id"]),
                )
            written += 1
        connection.commit()
    return {"written": written, "skipped": skipped}


def _receivable_actions(connection) -> list[dict[str, Any]]:
    actions = connection.execute(
        """
        SELECT ca.id, ca.action_type, ca.ex_date, ca.payment_date,
               ca.amount_per_share, ca.currency, ca.source_document_id,
               ca.component_group
        FROM corporate_actions ca
        JOIN instruments i ON i.id = ca.issuer_instrument_id
        WHERE i.symbol = 'BMOB3'
          AND ca.action_type IN ('DIVIDEND', 'JCP')
          AND ca.ex_date IS NOT NULL AND ca.payment_date IS NOT NULL
          AND ca.amount_per_share IS NOT NULL AND ca.currency = 'BRL'
        ORDER BY ca.ex_date, ca.id
        """
    ).fetchall()

    prepared: list[dict[str, Any]] = []
    gross_by_anchor: dict[int, Decimal] = {}
    for action in actions:
        holding = _holding(connection, action["ex_date"])
        if holding is None:
            continue
        gross_brl = Decimal(action["amount_per_share"]) * Decimal(holding["shares"])
        calibration_anchor = connection.execute(
            """
            SELECT id, as_of_date, associated_receivable_reported
            FROM other_net_assets_reported_anchors
            WHERE as_of_date >= ? AND as_of_date < ?
              AND CAST(associated_receivable_reported AS REAL) != 0
            ORDER BY as_of_date LIMIT 1
            """,
            (action["ex_date"], action["payment_date"]),
        ).fetchone()
        if calibration_anchor is not None:
            anchor_id = int(calibration_anchor["id"])
            gross_by_anchor[anchor_id] = gross_by_anchor.get(anchor_id, Decimal("0")) + gross_brl
        prepared.append(
            {
                "action": action,
                "holding": holding,
                "gross_brl": gross_brl,
                "calibration_anchor": calibration_anchor,
            }
        )

    calibration_by_anchor: dict[int, dict[str, Any]] = {}
    for item in prepared:
        calibration_anchor = item["calibration_anchor"]
        if calibration_anchor is None:
            continue
        anchor_id = int(calibration_anchor["id"])
        if anchor_id in calibration_by_anchor:
            continue
        anchor_date = calibration_anchor["as_of_date"]
        usd_fx = _nearest_fx(connection, "USD", anchor_date)
        brl_fx = _nearest_fx(connection, "BRL", anchor_date)
        total_gross_brl = gross_by_anchor[anchor_id]
        if usd_fx is None or brl_fx is None or total_gross_brl == 0:
            continue
        reported_usd = Decimal(calibration_anchor["associated_receivable_reported"])
        reported_nok = reported_usd * Decimal(usd_fx["rate"])
        gross_nok = total_gross_brl * Decimal(brl_fx["rate"])
        if gross_nok == 0:
            continue
        calibration_by_anchor[anchor_id] = {
            "factor": reported_nok / gross_nok,
            "metadata": {
                "anchor_id": anchor_id,
                "anchor_date": anchor_date,
                "reported_receivable_usd": decimal_text(reported_usd),
                "combined_gross_brl": decimal_text(total_gross_brl),
                "usd_nok": usd_fx["rate"],
                "brl_nok": brl_fx["rate"],
            },
        }

    result: list[dict[str, Any]] = []
    for item in prepared:
        action = item["action"]
        holding = item["holding"]
        gross_brl = item["gross_brl"]
        calibration_anchor = item["calibration_anchor"]
        factor = Decimal("1")
        quality = "ESTIMATED_GROSS"
        calibration: dict[str, Any] | None = None
        if calibration_anchor is not None:
            calibrated = calibration_by_anchor.get(int(calibration_anchor["id"]))
            if calibrated is not None:
                factor = calibrated["factor"]
                quality = "REPORTED_CALIBRATED"
                calibration = calibrated["metadata"]

        result.append(
            {
                "id": action["id"],
                "action_type": action["action_type"],
                "ex_date": action["ex_date"],
                "payment_date": action["payment_date"],
                "amount_per_share": action["amount_per_share"],
                "component_group": action["component_group"],
                "holding_id": holding["id"],
                "holding_shares": int(holding["shares"]),
                "gross_brl": gross_brl,
                "calibration_factor": factor,
                "quality": quality,
                "calibration": calibration,
                "source_document_id": action["source_document_id"],
            }
        )
    return result


def _receivable_for_day(connection, current_iso: str, actions: list[dict[str, Any]]) -> tuple[Decimal, str, list[dict[str, Any]]] | None:
    active = [action for action in actions if action["ex_date"] <= current_iso < action["payment_date"]]
    if not active:
        return Decimal("0"), "NONE", []

    brl_fx = _nearest_fx(connection, "BRL", current_iso)
    if brl_fx is None:
        return None

    rate = Decimal(brl_fx["rate"])
    total = Decimal("0")
    components: list[dict[str, Any]] = []
    qualities: set[str] = set()
    for action in active:
        amount_nok = action["gross_brl"] * rate * action["calibration_factor"]
        total += amount_nok
        qualities.add(action["quality"])
        components.append(
            {
                "corporate_action_id": action["id"],
                "action_type": action["action_type"],
                "ex_date": action["ex_date"],
                "payment_date": action["payment_date"],
                "component_group": action["component_group"],
                "holding_id": action["holding_id"],
                "holding_shares": action["holding_shares"],
                "gross_brl": decimal_text(action["gross_brl"]),
                "brl_nok": decimal_text(rate),
                "brl_nok_date": brl_fx["rate_date"],
                "calibration_factor": decimal_text(action["calibration_factor"]),
                "quality": action["quality"],
                "calibration": action["calibration"],
                "amount_nok": decimal_text(amount_nok),
            }
        )
    quality = "ESTIMATED_GROSS" if "ESTIMATED_GROSS" in qualities else "REPORTED_CALIBRATED"
    return total, quality, components


def _legacy_base(anchor) -> Decimal:
    return Decimal(anchor["base_other_net_assets_reported"])


def _anchor_base_ex_option(anchor) -> Decimal:
    raw = anchor["base_other_net_assets_ex_option_reported"]
    if raw is not None:
        return Decimal(raw)
    return _legacy_base(anchor) + Decimal(anchor["option_liability_reported"] or "0")


def _interpolated_base_ex_option(start_anchor, end_anchor, start_day: date, end_day: date, current: date) -> Decimal:
    """Preserve the old ONA path before the option grant, then decompose after grant."""
    legacy_start = _legacy_base(start_anchor)
    legacy_end = _legacy_base(end_anchor)
    elapsed = Decimal((current - start_day).days)
    span = Decimal((end_day - start_day).days)
    legacy_current = legacy_start + (legacy_end - legacy_start) * elapsed / span
    grant = date.fromisoformat(load_option_program()["program"]["grant_date"])

    # Når begge rapportankrene er etter opsjonsgrantet, er opsjonsforpliktelsen
    # allerede skilt ut ved begge endepunktene. Interpoler derfor mellom de
    # dekomponerte ONA-verdiene. Ellers blir opsjonsforpliktelsen i praksis
    # trukket fra to ganger mellom rapportdatoene.
    if grant <= start_day:
        decomposed_start = _anchor_base_ex_option(start_anchor)
        decomposed_end = _anchor_base_ex_option(end_anchor)
        return decomposed_start + (decomposed_end - decomposed_start) * elapsed / span

    end_option = Decimal(end_anchor["option_liability_reported"] or "0")
    if end_option == 0:
        return legacy_current
    if not (start_day < grant <= end_day) or current < grant:
        return legacy_current

    grant_fraction = Decimal((grant - start_day).days) / span
    legacy_at_grant = legacy_start + (legacy_end - legacy_start) * grant_fraction
    if current == grant:
        return legacy_at_grant

    post_elapsed = Decimal((current - grant).days)
    post_span = Decimal((end_day - grant).days)
    return legacy_at_grant + (_anchor_base_ex_option(end_anchor) - legacy_at_grant) * post_elapsed / post_span


def rebuild_daily_other_net_assets(
    database_path: str | None = None,
    *,
    end_date: str | None = None,
) -> dict[str, Any]:
    seed_bemobi_distributions(database_path)
    written = 0
    skipped_fx = 0
    skipped_receivable_fx = 0
    skipped_option_inputs = 0
    option_model_days = 0
    with get_connection(database_path) as connection:
        anchors = connection.execute(
            """
            SELECT r.id, r.as_of_date, r.other_net_assets_reported,
                   r.associated_receivable_reported, r.base_other_net_assets_reported,
                   r.option_liability_reported, r.base_other_net_assets_ex_option_reported
            FROM other_net_assets_reported_anchors r
            JOIN other_net_assets_anchors n ON n.reported_anchor_id = r.id
            ORDER BY r.as_of_date
            """
        ).fetchall()
        if not anchors:
            return {"written": 0, "error": "no normalized other-net-assets anchors"}

        start = date.fromisoformat(anchors[0]["as_of_date"])
        if end_date is None:
            row = connection.execute("SELECT MAX(estimate_date) AS d FROM cash_daily_estimates").fetchone()
            end = date.fromisoformat(row["d"]) if row is not None and row["d"] else date.fromisoformat(anchors[-1]["as_of_date"])
        else:
            end = date.fromisoformat(end_date)
        if end < start:
            return {"written": 0, "from": start.isoformat(), "to": end.isoformat()}

        receivable_actions = _receivable_actions(connection)
        anchor_dates = [date.fromisoformat(row["as_of_date"]) for row in anchors]
        current = start
        while current <= end:
            current_iso = current.isoformat()
            previous_index = max(i for i, d in enumerate(anchor_dates) if d <= current)
            start_anchor = anchors[previous_index]
            start_day = anchor_dates[previous_index]

            if current == start_day:
                end_anchor = start_anchor
                base_usd = _anchor_base_ex_option(start_anchor)
                quality = "REPORTED_ANCHOR"
            elif previous_index + 1 < len(anchors):
                end_anchor = anchors[previous_index + 1]
                end_day = anchor_dates[previous_index + 1]
                base_usd = _interpolated_base_ex_option(
                    start_anchor, end_anchor, start_day, end_day, current
                )
                quality = "INTERPOLATED"
            else:
                end_anchor = None
                base_usd = _anchor_base_ex_option(start_anchor)
                quality = "FORECAST_PARTIAL"

            usd_fx = _nearest_fx(connection, "USD", current_iso)
            if usd_fx is None:
                skipped_fx += 1
                current += timedelta(days=1)
                continue
            usd_nok = Decimal(usd_fx["rate"])
            base_nok = base_usd * usd_nok

            receivable_result = _receivable_for_day(connection, current_iso, receivable_actions)
            if receivable_result is None:
                skipped_receivable_fx += 1
                current += timedelta(days=1)
                continue
            receivable_nok, receivable_quality, receivable_components = receivable_result

            option = option_liability_for_day(connection, current_iso)
            if option is None:
                skipped_option_inputs += 1
                current += timedelta(days=1)
                continue
            option_liability_nok = Decimal(option["liability_nok"])
            option_liability_usd = Decimal(option["liability_usd"])
            if option["quality"] != "NONE":
                option_model_days += 1

            amount_nok = base_nok + receivable_nok - option_liability_nok
            amount_usd_equivalent = amount_nok / usd_nok if usd_nok != 0 else base_usd

            if current == start_day:
                reported_total_usd = Decimal(start_anchor["other_net_assets_reported"])
                reported_receivable_usd = Decimal(start_anchor["associated_receivable_reported"])
                reported_option_usd = Decimal(start_anchor["option_liability_reported"] or "0")
                tolerance = Decimal("0.01")
                if abs(amount_usd_equivalent - reported_total_usd) > tolerance:
                    raise ValueError(
                        f"Option-aware ONA does not reconcile at {current_iso}: "
                        f"modeled USD {amount_usd_equivalent} vs reported USD {reported_total_usd}"
                    )
                if reported_receivable_usd == 0 and receivable_nok != 0:
                    raise ValueError(f"Unexpected active receivable at zero-receivable report anchor {current_iso}")
                if abs(option_liability_usd - reported_option_usd) > tolerance:
                    raise ValueError(
                        f"Option liability does not reconcile at {current_iso}: "
                        f"modeled USD {option_liability_usd} vs reported USD {reported_option_usd}"
                    )

            payload = {
                "date": current_iso,
                "base_ex_option_usd": decimal_text(base_usd),
                "base_ex_option_nok": decimal_text(base_nok),
                "usd_nok": decimal_text(usd_nok),
                "usd_fx_rate_id": usd_fx["id"],
                "associated_receivable_nok": decimal_text(receivable_nok),
                "receivable_quality": receivable_quality,
                "receivable_components": receivable_components,
                "option_liability_nok": decimal_text(option_liability_nok),
                "option_liability_usd": decimal_text(option_liability_usd),
                "option_quality": option["quality"],
                "option_inputs": option["inputs"],
                "start_anchor_id": start_anchor["id"],
                "end_anchor_id": end_anchor["id"] if end_anchor is not None else None,
                "quality": quality,
            }
            if quality == "REPORTED_ANCHOR":
                notes = "Reported ONA anchor; Bemobi receivable and cash-settled option obligation are decomposed explicitly."
            elif quality == "INTERPOLATED":
                notes = (
                    "Base ONA is reconstructed in USD without changing the pre-grant path; from the 15 Sep 2025 grant the cash-settled option obligation is separated and marked to market."
                )
            else:
                notes = (
                    "Latest base ONA excluding the option obligation is carried forward in USD; Bemobi receivables remain event-driven and the cash-settled option obligation is marked to market using the latest reported valuation assumptions."
                )

            connection.execute(
                """
                INSERT INTO other_net_assets_daily_estimates(
                    estimate_date, amount_usd, usd_nok_rate, amount_nok, quality,
                    start_anchor_id, end_anchor_id, inputs_hash, notes,
                    base_amount_usd, base_amount_nok, associated_receivable_nok,
                    receivable_quality, receivable_components_json,
                    option_liability_nok, option_liability_usd,
                    option_fair_value_per_option_nok, option_recognition_fraction,
                    option_spot_nok, option_strike_nok, option_quality, option_inputs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(estimate_date) DO UPDATE SET
                    amount_usd = excluded.amount_usd,
                    usd_nok_rate = excluded.usd_nok_rate,
                    amount_nok = excluded.amount_nok,
                    quality = excluded.quality,
                    start_anchor_id = excluded.start_anchor_id,
                    end_anchor_id = excluded.end_anchor_id,
                    inputs_hash = excluded.inputs_hash,
                    notes = excluded.notes,
                    base_amount_usd = excluded.base_amount_usd,
                    base_amount_nok = excluded.base_amount_nok,
                    associated_receivable_nok = excluded.associated_receivable_nok,
                    receivable_quality = excluded.receivable_quality,
                    receivable_components_json = excluded.receivable_components_json,
                    option_liability_nok = excluded.option_liability_nok,
                    option_liability_usd = excluded.option_liability_usd,
                    option_fair_value_per_option_nok = excluded.option_fair_value_per_option_nok,
                    option_recognition_fraction = excluded.option_recognition_fraction,
                    option_spot_nok = excluded.option_spot_nok,
                    option_strike_nok = excluded.option_strike_nok,
                    option_quality = excluded.option_quality,
                    option_inputs_json = excluded.option_inputs_json,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (
                    current_iso, decimal_text(amount_usd_equivalent), decimal_text(usd_nok),
                    decimal_text(amount_nok), quality, start_anchor["id"],
                    end_anchor["id"] if end_anchor is not None else None,
                    _hash(payload), notes, decimal_text(base_usd), decimal_text(base_nok),
                    decimal_text(receivable_nok), receivable_quality,
                    json.dumps(receivable_components, sort_keys=True, ensure_ascii=False),
                    decimal_text(option_liability_nok), decimal_text(option_liability_usd),
                    decimal_text(option["fair_value_per_option_nok"]) if option["fair_value_per_option_nok"] is not None else None,
                    decimal_text(option["recognition_fraction"]),
                    decimal_text(option["spot_nok"]) if option["spot_nok"] is not None else None,
                    decimal_text(option["strike_nok"]), option["quality"],
                    json.dumps(option["inputs"], sort_keys=True, ensure_ascii=False),
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
        "skipped_missing_receivable_fx": skipped_receivable_fx,
        "skipped_missing_option_inputs": skipped_option_inputs,
        "receivable_actions": len(receivable_actions),
        "calibrated_receivable_actions": sum(1 for item in receivable_actions if item["quality"] == "REPORTED_CALIBRATED"),
        "option_model_days": option_model_days,
    }


def other_net_assets_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        reported = connection.execute(
            """
            SELECT COUNT(*) n, MIN(as_of_date) min_date, MAX(as_of_date) max_date,
                   SUM(CASE WHEN CAST(associated_receivable_reported AS REAL) != 0 THEN 1 ELSE 0 END) receivable_anchors,
                   SUM(CASE WHEN CAST(option_liability_reported AS REAL) != 0 THEN 1 ELSE 0 END) option_liability_anchors
            FROM other_net_assets_reported_anchors
            """
        ).fetchone()
        daily = connection.execute(
            """
            SELECT COUNT(*) n, MIN(estimate_date) min_date, MAX(estimate_date) max_date,
                   SUM(CASE WHEN quality = 'FORECAST_PARTIAL' THEN 1 ELSE 0 END) forecast_partial,
                   SUM(CASE WHEN CAST(associated_receivable_nok AS REAL) != 0 THEN 1 ELSE 0 END) receivable_days,
                   SUM(CASE WHEN receivable_quality = 'ESTIMATED_GROSS' THEN 1 ELSE 0 END) estimated_receivable_days,
                   SUM(CASE WHEN CAST(option_liability_nok AS REAL) != 0 THEN 1 ELSE 0 END) option_liability_days,
                   SUM(CASE WHEN option_quality = 'FORECAST_MARK_TO_MARKET' THEN 1 ELSE 0 END) option_forecast_days
            FROM other_net_assets_daily_estimates
            """
        ).fetchone()
        latest = connection.execute(
            """
            SELECT estimate_date, amount_usd, usd_nok_rate, amount_nok, quality,
                   base_amount_usd, base_amount_nok, associated_receivable_nok,
                   receivable_quality, option_liability_nok, option_liability_usd,
                   option_fair_value_per_option_nok, option_recognition_fraction,
                   option_spot_nok, option_strike_nok, option_quality, notes
            FROM other_net_assets_daily_estimates ORDER BY estimate_date DESC LIMIT 1
            """
        ).fetchone()
        return {
            "status": "ok" if daily["n"] else "empty",
            "reported_anchors": {
                "count": reported["n"], "from": reported["min_date"], "to": reported["max_date"],
                "receivable_anchors": reported["receivable_anchors"],
                "option_liability_anchors": reported["option_liability_anchors"],
            },
            "daily": {
                "count": daily["n"], "from": daily["min_date"], "to": daily["max_date"],
                "forecast_partial": daily["forecast_partial"],
                "receivable_days": daily["receivable_days"],
                "estimated_receivable_days": daily["estimated_receivable_days"],
                "option_liability_days": daily["option_liability_days"],
                "option_forecast_days": daily["option_forecast_days"],
            },
            "latest": dict(latest) if latest is not None else None,
        }

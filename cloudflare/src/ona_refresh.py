from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from cash_refresh import decimal_text, nearest_fx, stable_hash
from option_refresh import OPTION_MANIFEST, option_liability_for_day
from repository import D1WriteRepository


def _to_date(value: str) -> date:
    return date.fromisoformat(value)


async def _holding(repository: D1WriteRepository, as_of_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT id,shares,effective_from,effective_to
        FROM bemobi_holdings
        WHERE effective_from<=?
          AND (effective_to IS NULL OR effective_to>=?)
        ORDER BY effective_from DESC,id DESC
        LIMIT 1
        """,
        (as_of_date, as_of_date),
    )


async def _receivable_actions(repository: D1WriteRepository) -> list[dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT ca.id,ca.action_type,ca.ex_date,ca.payment_date,ca.amount_per_share,
               ca.currency,ca.source_document_id,ca.component_group
        FROM corporate_actions ca
        JOIN instruments i ON i.id=ca.issuer_instrument_id
        WHERE i.symbol='BMOB3'
          AND ca.action_type IN ('DIVIDEND','JCP')
          AND ca.ex_date IS NOT NULL
          AND ca.payment_date IS NOT NULL
          AND ca.amount_per_share IS NOT NULL
          AND ca.currency='BRL'
        ORDER BY ca.ex_date,ca.id
        """
    )
    prepared: list[dict[str, Any]] = []
    gross_by_anchor: dict[int, Decimal] = {}
    for action in rows:
        holding = await _holding(repository, str(action["ex_date"]))
        if holding is None:
            continue
        gross_brl = Decimal(str(action["amount_per_share"])) * Decimal(str(holding["shares"]))
        calibration = await repository.first(
            """
            SELECT id,as_of_date,associated_receivable_reported
            FROM other_net_assets_reported_anchors
            WHERE as_of_date>=? AND as_of_date<?
              AND CAST(associated_receivable_reported AS REAL)!=0
            ORDER BY as_of_date
            LIMIT 1
            """,
            (action["ex_date"], action["payment_date"]),
        )
        if calibration is not None:
            anchor_id = int(calibration["id"])
            gross_by_anchor[anchor_id] = gross_by_anchor.get(anchor_id, Decimal("0")) + gross_brl
        prepared.append(
            {
                "action": action,
                "holding": holding,
                "gross_brl": gross_brl,
                "calibration": calibration,
            }
        )

    calibration_by_anchor: dict[int, dict[str, Any]] = {}
    for item in prepared:
        anchor = item["calibration"]
        if anchor is None:
            continue
        anchor_id = int(anchor["id"])
        if anchor_id in calibration_by_anchor:
            continue
        usd = await nearest_fx(repository, "USD", str(anchor["as_of_date"]))
        brl = await nearest_fx(repository, "BRL", str(anchor["as_of_date"]))
        gross_brl = gross_by_anchor.get(anchor_id, Decimal("0"))
        if usd is None or brl is None or gross_brl == 0:
            continue
        reported_usd = Decimal(str(anchor["associated_receivable_reported"]))
        reported_nok = reported_usd * Decimal(str(usd["rate"]))
        gross_nok = gross_brl * Decimal(str(brl["rate"]))
        if gross_nok == 0:
            continue
        calibration_by_anchor[anchor_id] = {
            "factor": reported_nok / gross_nok,
            "metadata": {
                "anchor_id": anchor_id,
                "anchor_date": anchor["as_of_date"],
                "reported_receivable_usd": decimal_text(reported_usd),
                "combined_gross_brl": decimal_text(gross_brl),
                "usd_nok": usd["rate"],
                "brl_nok": brl["rate"],
            },
        }

    result: list[dict[str, Any]] = []
    for item in prepared:
        action = item["action"]
        holding = item["holding"]
        factor = Decimal("1")
        quality = "ESTIMATED_GROSS"
        calibration_meta = None
        anchor = item["calibration"]
        if anchor is not None:
            calibrated = calibration_by_anchor.get(int(anchor["id"]))
            if calibrated is not None:
                factor = calibrated["factor"]
                quality = "REPORTED_CALIBRATED"
                calibration_meta = calibrated["metadata"]
        result.append(
            {
                "id": int(action["id"]),
                "action_type": action["action_type"],
                "ex_date": action["ex_date"],
                "payment_date": action["payment_date"],
                "component_group": action["component_group"],
                "holding_id": int(holding["id"]),
                "holding_shares": int(holding["shares"]),
                "gross_brl": item["gross_brl"],
                "calibration_factor": factor,
                "quality": quality,
                "calibration": calibration_meta,
            }
        )
    return result


async def _receivable_for_day(
    repository: D1WriteRepository,
    as_of_date: str,
    actions: list[dict[str, Any]],
) -> tuple[Decimal, str, list[dict[str, Any]]] | None:
    active = [
        item for item in actions
        if item["ex_date"] <= as_of_date < item["payment_date"]
    ]
    if not active:
        return Decimal("0"), "NONE", []
    brl = await nearest_fx(repository, "BRL", as_of_date)
    if brl is None:
        return None
    rate = Decimal(str(brl["rate"]))
    total = Decimal("0")
    qualities: set[str] = set()
    components: list[dict[str, Any]] = []
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
                "brl_nok_date": brl["rate_date"],
                "calibration_factor": decimal_text(action["calibration_factor"]),
                "quality": action["quality"],
                "calibration": action["calibration"],
                "amount_nok": decimal_text(amount_nok),
            }
        )
    quality = (
        "ESTIMATED_GROSS"
        if "ESTIMATED_GROSS" in qualities
        else "REPORTED_CALIBRATED"
    )
    return total, quality, components


def _legacy_base(anchor: dict[str, Any]) -> Decimal:
    return Decimal(str(anchor["base_other_net_assets_reported"]))


def _base_ex_option(anchor: dict[str, Any]) -> Decimal:
    raw = anchor.get("base_other_net_assets_ex_option_reported")
    if raw is not None:
        return Decimal(str(raw))
    return _legacy_base(anchor) + Decimal(str(anchor.get("option_liability_reported") or "0"))


def _interpolated_base_ex_option(
    start_anchor: dict[str, Any],
    end_anchor: dict[str, Any],
    start_day: date,
    end_day: date,
    current: date,
) -> Decimal:
    span = Decimal((end_day - start_day).days)
    elapsed = Decimal((current - start_day).days)
    legacy_start = _legacy_base(start_anchor)
    legacy_end = _legacy_base(end_anchor)
    legacy_current = legacy_start + (legacy_end - legacy_start) * elapsed / span

    end_option = Decimal(str(end_anchor.get("option_liability_reported") or "0"))
    if end_option == 0:
        return legacy_current
    grant = _to_date(OPTION_MANIFEST["program"]["grant_date"])
    if not (start_day < grant <= end_day) or current < grant:
        return legacy_current
    grant_fraction = Decimal((grant - start_day).days) / span
    legacy_at_grant = legacy_start + (legacy_end - legacy_start) * grant_fraction
    if current == grant:
        return legacy_at_grant
    return legacy_at_grant + (
        _base_ex_option(end_anchor) - legacy_at_grant
    ) * Decimal((current - grant).days) / Decimal((end_day - grant).days)


async def rebuild_other_net_assets_for_date(
    repository: D1WriteRepository,
    *,
    as_of_date: str,
) -> dict[str, Any]:
    anchors = await repository.all(
        """
        SELECT r.id,r.as_of_date,r.other_net_assets_reported,
               r.associated_receivable_reported,r.base_other_net_assets_reported,
               r.option_liability_reported,r.base_other_net_assets_ex_option_reported
        FROM other_net_assets_reported_anchors r
        JOIN other_net_assets_anchors n ON n.reported_anchor_id=r.id
        ORDER BY r.as_of_date
        """
    )
    if not anchors:
        raise ValueError("Mangler normaliserte ONA-ankere")

    current = _to_date(as_of_date)
    eligible = [
        index for index, anchor in enumerate(anchors)
        if _to_date(str(anchor["as_of_date"])) <= current
    ]
    if not eligible:
        raise ValueError("ONA-dato er før første rapporterte anker")
    previous_index = max(eligible)
    start_anchor = anchors[previous_index]
    start_day = _to_date(str(start_anchor["as_of_date"]))

    if current == start_day:
        end_anchor = start_anchor
        base_usd = _base_ex_option(start_anchor)
        quality = "REPORTED_ANCHOR"
    elif previous_index + 1 < len(anchors):
        end_anchor = anchors[previous_index + 1]
        end_day = _to_date(str(end_anchor["as_of_date"]))
        base_usd = _interpolated_base_ex_option(
            start_anchor, end_anchor, start_day, end_day, current
        )
        quality = "INTERPOLATED"
    else:
        end_anchor = None
        base_usd = _base_ex_option(start_anchor)
        quality = "FORECAST_PARTIAL"

    usd = await nearest_fx(repository, "USD", as_of_date)
    if usd is None:
        raise ValueError("Mangler USD/NOK for ONA")
    usd_nok = Decimal(str(usd["rate"]))
    base_nok = base_usd * usd_nok

    receivable = await _receivable_for_day(
        repository,
        as_of_date,
        await _receivable_actions(repository),
    )
    if receivable is None:
        raise ValueError("Mangler BRL/NOK for aktiv Bemobi-fordring")
    receivable_nok, receivable_quality, receivable_components = receivable

    option = await option_liability_for_day(repository, as_of_date)
    if option is None:
        raise ValueError("Mangler input til opsjonsforpliktelsen")
    option_nok = Decimal(option["liability_nok"])
    amount_nok = base_nok + receivable_nok - option_nok
    amount_usd = amount_nok / usd_nok
    payload = {
        "date": as_of_date,
        "base_amount_usd": decimal_text(base_usd),
        "usd_nok_rate": decimal_text(usd_nok),
        "usd_nok_rate_id": int(usd["id"]),
        "receivable_nok": decimal_text(receivable_nok),
        "receivable_quality": receivable_quality,
        "receivable_components": receivable_components,
        "option_inputs": option["inputs"],
        "start_anchor_id": int(start_anchor["id"]),
        "end_anchor_id": int(end_anchor["id"]) if end_anchor is not None else None,
    }

    await repository.run(
        """
        INSERT INTO other_net_assets_daily_estimates(
            estimate_date,amount_usd,usd_nok_rate,amount_nok,quality,
            start_anchor_id,end_anchor_id,inputs_hash,notes,
            base_amount_usd,base_amount_nok,associated_receivable_nok,
            receivable_quality,receivable_components_json,
            option_liability_nok,option_liability_usd,
            option_fair_value_per_option_nok,option_recognition_fraction,
            option_spot_nok,option_strike_nok,option_quality,option_inputs_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(estimate_date) DO UPDATE SET
            amount_usd=excluded.amount_usd,
            usd_nok_rate=excluded.usd_nok_rate,
            amount_nok=excluded.amount_nok,
            quality=excluded.quality,
            start_anchor_id=excluded.start_anchor_id,
            end_anchor_id=excluded.end_anchor_id,
            inputs_hash=excluded.inputs_hash,
            notes=excluded.notes,
            base_amount_usd=excluded.base_amount_usd,
            base_amount_nok=excluded.base_amount_nok,
            associated_receivable_nok=excluded.associated_receivable_nok,
            receivable_quality=excluded.receivable_quality,
            receivable_components_json=excluded.receivable_components_json,
            option_liability_nok=excluded.option_liability_nok,
            option_liability_usd=excluded.option_liability_usd,
            option_fair_value_per_option_nok=excluded.option_fair_value_per_option_nok,
            option_recognition_fraction=excluded.option_recognition_fraction,
            option_spot_nok=excluded.option_spot_nok,
            option_strike_nok=excluded.option_strike_nok,
            option_quality=excluded.option_quality,
            option_inputs_json=excluded.option_inputs_json,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (
            as_of_date,
            decimal_text(amount_usd),
            decimal_text(usd_nok),
            decimal_text(amount_nok),
            quality,
            int(start_anchor["id"]),
            int(end_anchor["id"]) if end_anchor is not None else None,
            stable_hash(payload),
            "Daily ONA: base ONA ex option + active Bemobi receivables - cash-settled option liability.",
            decimal_text(base_usd),
            decimal_text(base_nok),
            decimal_text(receivable_nok),
            receivable_quality,
            json.dumps(receivable_components, ensure_ascii=False, sort_keys=True),
            decimal_text(option_nok),
            decimal_text(option["liability_usd"]),
            (
                decimal_text(option["fair_value_per_option_nok"])
                if option["fair_value_per_option_nok"] is not None
                else None
            ),
            decimal_text(option["recognition_fraction"]),
            decimal_text(option["spot_nok"]) if option["spot_nok"] is not None else None,
            decimal_text(option["strike_nok"]),
            option["quality"],
            json.dumps(option["inputs"], ensure_ascii=False, sort_keys=True),
        ),
    )
    return {
        "written": 1,
        "date": as_of_date,
        "amount_nok": decimal_text(amount_nok),
        "quality": quality,
        "receivable_nok": decimal_text(receivable_nok),
        "option_liability_nok": decimal_text(option_nok),
        "option_quality": option["quality"],
    }

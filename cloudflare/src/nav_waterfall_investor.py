from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from nav_waterfall_live import nav_waterfall_summary as base_nav_waterfall_summary

MILLION = Decimal("1000000")
_BUYBACK_PERIOD_RE = re.compile(
    r"during\s+(20\d{2}-\d{2}-\d{2})[–-](20\d{2}-\d{2}-\d{2})",
    re.I,
)


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _component(
    *,
    key: str,
    label: str,
    amount_nok: Decimal,
    anchor_shares: int,
    note: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "amount_mnok": float(amount_nok / MILLION),
        "per_share_nok": float(amount_nok / Decimal(anchor_shares)),
        "impact_kind": "TOTAL_AND_PER_SHARE",
        "note": note,
    }


def reclassify_waterfall(
    result: dict[str, Any],
    *,
    cash_change_nok: Decimal,
    buyback_cash_nok: Decimal,
    bemobi_gross_cash_nok: Decimal,
    bemobi_withholding_nok: Decimal,
    anchor_bemobi_receivable_nok: Decimal,
    current_bemobi_receivable_nok: Decimal,
    buyback_metadata: dict[str, Any] | None = None,
    bemobi_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not result.get("ready"):
        return result

    anchor = result.get("anchor") or {}
    anchor_shares = int(anchor.get("shares_outstanding") or 0)
    if anchor_shares <= 0:
        return result

    components = list(result.get("components") or [])
    original_by_key = {str(item.get("key")): item for item in components}
    original_ona = original_by_key.get("ona_ex_option")
    if original_ona is None:
        return result

    bemobi_net_cash_nok = bemobi_gross_cash_nok + bemobi_withholding_nok
    other_cash_nok = cash_change_nok - buyback_cash_nok - bemobi_net_cash_nok
    receivable_change_nok = current_bemobi_receivable_nok - anchor_bemobi_receivable_nok
    original_ona_nok = _decimal(original_ona.get("amount_mnok")) * MILLION
    base_ona_change_nok = original_ona_nok - receivable_change_nok

    replacements: dict[str, list[dict[str, Any]]] = {
        "buyback_cash": [
            _component(
                key="buyback_cash",
                label="Tilbakekjøp – kontantbruk",
                amount_nok=buyback_cash_nok,
                anchor_shares=anchor_shares,
                note=(
                    "Bekreftede tilbakekjøp etter rapportankeret. Daglige NewsWeb-"
                    "transaksjoner brukes når de finnes; ukesrader brukes ellers."
                ),
            ),
            _component(
                key="bemobi_cash_received",
                label="Bemobi-utbytte/renter – mottatt",
                amount_nok=bemobi_net_cash_nok,
                anchor_shares=anchor_shares,
                note=(
                    "Kontantmottak fra Bemobi etter rapportankeret, netto dokumentert "
                    "skattetrekk på renter. Utbytte og renter vises separat fra øvrig cash."
                ),
            ),
        ],
        "other_cash": [
            _component(
                key="other_cash",
                label="Øvrig kontantendring",
                amount_nok=other_cash_nok,
                anchor_shares=anchor_shares,
                note=(
                    "Kontantendring som gjenstår etter at tilbakekjøp og mottatt "
                    "Bemobi-utbytte/renter er skilt ut."
                ),
            )
        ],
        "ona_ex_option": [
            _component(
                key="bemobi_receivable",
                label="Bemobi-utbytte/renter – til gode",
                amount_nok=receivable_change_nok,
                anchor_shares=anchor_shares,
                note=(
                    "Endring i opptjent Bemobi-utbytte/renter som er ex-rettighet, men ennå "
                    "ikke utbetalt. Ved betaling flyttes beløpet fra fordring til cash."
                ),
            ),
            _component(
                key="ona_ex_option",
                label="ONA ekskl. opsjon og Bemobi-fordring",
                amount_nok=base_ona_change_nok,
                anchor_shares=anchor_shares,
                note=(
                    "Endring i øvrige nettoeiendeler etter at både opsjonsforpliktelsen "
                    "og Bemobi-fordringen er skilt ut."
                ),
            ),
        ],
    }

    rebuilt: list[dict[str, Any]] = []
    for item in components:
        key = str(item.get("key"))
        if key in replacements:
            rebuilt.extend(replacements[key])
        else:
            rebuilt.append(item)
    result["components"] = rebuilt

    buyback_info = dict(result.get("buybacks") or {})
    buyback_info.update(
        {
            "modeled_cash_mnok": float(buyback_cash_nok / MILLION),
            **(buyback_metadata or {}),
        }
    )
    result["buybacks"] = buyback_info
    result["bemobi_distributions"] = {
        "gross_cash_mnok": float(bemobi_gross_cash_nok / MILLION),
        "withholding_mnok": float(bemobi_withholding_nok / MILLION),
        "net_cash_mnok": float(bemobi_net_cash_nok / MILLION),
        "anchor_receivable_mnok": float(anchor_bemobi_receivable_nok / MILLION),
        "current_receivable_mnok": float(current_bemobi_receivable_nok / MILLION),
        "receivable_change_mnok": float(receivable_change_nok / MILLION),
        **(bemobi_metadata or {}),
    }
    result["note"] = (
        str(result.get("note") or "")
        + " Kontantbroen skiller tilbakekjøp og mottatt Bemobi-utbytte/renter fra øvrig cash; "
        "opptjent, ikke utbetalt Bemobi-utbytte/renter vises separat som fordring."
    ).strip()
    return result


async def _cash_change(
    repository, anchor_date: str, as_of_date: str, result: dict[str, Any]
) -> Decimal:
    values: dict[str, Decimal] = {}
    for day in (anchor_date, as_of_date):
        row = await repository.first(
            "SELECT cash_nok FROM cash_daily_estimates WHERE estimate_date=? LIMIT 1",
            (day,),
        )
        if row is not None:
            values[day] = Decimal(str(row["cash_nok"]))
    if anchor_date in values and as_of_date in values:
        return values[as_of_date] - values[anchor_date]

    by_key = {str(item.get("key")): item for item in result.get("components") or []}
    return (
        _decimal((by_key.get("buyback_cash") or {}).get("amount_mnok"))
        + _decimal((by_key.get("other_cash") or {}).get("amount_mnok"))
    ) * MILLION


async def _cash_breakdown(
    repository, *, anchor_date: str, as_of_date: str
) -> dict[str, Any]:
    rows = await repository.all(
        """
        SELECT movement_date, movement_type, amount_nok, description,
               external_movement_id, buyback_id
        FROM cash_movements
        WHERE movement_date > ? AND movement_date <= ?
          AND movement_type IN (
              'OTELLO_BUYBACK', 'OTELLO_BUYBACK_DAILY',
              'BEMOBI_DIVIDEND', 'BEMOBI_JCP', 'TAX'
          )
        ORDER BY movement_date, id
        """,
        (anchor_date, as_of_date),
    )

    copied = [dict(row) for row in rows]
    daily_totals: dict[int, Decimal] = {}
    weekly_totals: dict[int, Decimal] = {}
    for row in copied:
        buyback_id = row.get("buyback_id")
        if buyback_id is None:
            continue
        identifier = int(buyback_id)
        amount = Decimal(str(row.get("amount_nok") or "0"))
        movement_type = str(row.get("movement_type") or "")
        if movement_type == "OTELLO_BUYBACK_DAILY":
            daily_totals[identifier] = (
                daily_totals.get(identifier, Decimal("0")) + amount
            )
        elif movement_type == "OTELLO_BUYBACK":
            match = _BUYBACK_PERIOD_RE.search(str(row.get("description") or ""))
            if match and match.group(1) <= anchor_date < str(row.get("movement_date")):
                continue
            weekly_totals[identifier] = (
                weekly_totals.get(identifier, Decimal("0")) + amount
            )
    daily_buyback_ids = {
        identifier
        for identifier, daily_total in daily_totals.items()
        if identifier in weekly_totals
        and abs(daily_total - weekly_totals[identifier]) <= Decimal("0.01")
    }

    buyback_cash = Decimal("0")
    bemobi_gross = Decimal("0")
    bemobi_withholding = Decimal("0")
    weekly_rows = 0
    daily_rows = 0
    weekly_superseded = 0
    cross_anchor_weekly_excluded = 0
    bemobi_receipt_rows = 0
    withholding_rows = 0

    for row in copied:
        movement_type = str(row.get("movement_type") or "")
        amount = Decimal(str(row.get("amount_nok") or "0"))
        description = str(row.get("description") or "")
        external_id = str(row.get("external_movement_id") or "")

        if movement_type == "OTELLO_BUYBACK_DAILY":
            buyback_id = row.get("buyback_id")
            if (
                buyback_id is not None
                and int(buyback_id) in weekly_totals
                and int(buyback_id) not in daily_buyback_ids
            ):
                continue
            buyback_cash += amount
            daily_rows += 1
            continue
        if movement_type == "OTELLO_BUYBACK":
            buyback_id = row.get("buyback_id")
            if buyback_id is not None and int(buyback_id) in daily_buyback_ids:
                weekly_superseded += 1
                continue
            match = _BUYBACK_PERIOD_RE.search(description)
            if match and match.group(1) <= anchor_date < str(row.get("movement_date")):
                cross_anchor_weekly_excluded += 1
                continue
            buyback_cash += amount
            weekly_rows += 1
            continue
        if movement_type in {"BEMOBI_DIVIDEND", "BEMOBI_JCP"}:
            bemobi_gross += amount
            bemobi_receipt_rows += 1
            continue
        if movement_type == "TAX" and (
            external_id.startswith("bemobi-withholding:")
            or description.lower().startswith("bemobi jcp withholding")
        ):
            bemobi_withholding += amount
            withholding_rows += 1

    return {
        "buyback_cash_nok": buyback_cash,
        "bemobi_gross_cash_nok": bemobi_gross,
        "bemobi_withholding_nok": bemobi_withholding,
        "buyback_metadata": {
            "weekly_cash_rows": weekly_rows,
            "daily_cash_rows": daily_rows,
            "weekly_superseded": weekly_superseded,
            "movement_count": weekly_rows + daily_rows,
            "cross_anchor_excluded": cross_anchor_weekly_excluded,
            "source_mode": "DAILY_WHEN_AVAILABLE_WEEKLY_FALLBACK",
        },
        "bemobi_metadata": {
            "cash_receipt_rows": bemobi_receipt_rows,
            "withholding_rows": withholding_rows,
        },
    }


async def _receivable(repository, day: str) -> tuple[Decimal, str | None]:
    row = await repository.first(
        """
        SELECT associated_receivable_nok, receivable_quality
        FROM other_net_assets_daily_estimates
        WHERE estimate_date=? LIMIT 1
        """,
        (day,),
    )
    if row is None:
        return Decimal("0"), None
    return Decimal(str(row.get("associated_receivable_nok") or "0")), row.get(
        "receivable_quality"
    )


async def nav_waterfall_summary(repository) -> dict[str, Any]:
    result = await base_nav_waterfall_summary(repository)
    if not result.get("ready"):
        return result

    anchor_date = str(result["anchor_date"])
    as_of_date = str(result["as_of_date"])
    cash = await _cash_breakdown(
        repository,
        anchor_date=anchor_date,
        as_of_date=as_of_date,
    )
    cash_change = await _cash_change(repository, anchor_date, as_of_date, result)
    anchor_receivable, anchor_receivable_quality = await _receivable(
        repository, anchor_date
    )
    current_receivable, current_receivable_quality = await _receivable(
        repository, as_of_date
    )

    cash["bemobi_metadata"].update(
        {
            "anchor_receivable_quality": anchor_receivable_quality,
            "current_receivable_quality": current_receivable_quality,
        }
    )
    return reclassify_waterfall(
        result,
        cash_change_nok=cash_change,
        buyback_cash_nok=cash["buyback_cash_nok"],
        bemobi_gross_cash_nok=cash["bemobi_gross_cash_nok"],
        bemobi_withholding_nok=cash["bemobi_withholding_nok"],
        anchor_bemobi_receivable_nok=anchor_receivable,
        current_bemobi_receivable_nok=current_receivable,
        buyback_metadata=cash["buyback_metadata"],
        bemobi_metadata=cash["bemobi_metadata"],
    )

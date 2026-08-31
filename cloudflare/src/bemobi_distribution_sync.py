from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

try:
    from .option_liability import decimal_text
except ImportError:
    from option_liability import decimal_text

MAX_FX_LOOKBACK_DAYS = 7


async def _nearest_brl_nok(repository, payment_date: str) -> dict[str, Any] | None:
    floor = (date.fromisoformat(payment_date) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT fr.id, substr(fr.observed_at, 1, 10) AS rate_date, fr.rate,
               fr.source_document_id, s.code AS source_code
        FROM fx_rates fr
        JOIN sources s ON s.id = fr.source_id
        WHERE fr.base_currency = 'BRL' AND fr.quote_currency = 'NOK'
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
        (payment_date, floor),
    )


async def _holding(repository, entitlement_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT id, shares, effective_from, effective_to
        FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """,
        (entitlement_date, entitlement_date),
    )


def _tax_per_share(action: dict[str, Any]) -> tuple[Decimal, str] | None:
    gross = Decimal(str(action["amount_per_share"]))
    if action.get("net_amount_per_share") is not None:
        tax = gross - Decimal(str(action["net_amount_per_share"]))
        return (tax, "PUBLISHED_NET") if tax > 0 else None
    if action.get("withholding_rate") is not None:
        tax = gross * Decimal(str(action["withholding_rate"]))
        return (tax, "PUBLISHED_WITHHOLDING_RATE") if tax > 0 else None
    return None


async def _upsert_receipt(
    repository,
    *,
    action: dict[str, Any],
    holding: dict[str, Any],
    fx: dict[str, Any],
) -> str:
    gross_per_share = Decimal(str(action["amount_per_share"]))
    shares = Decimal(int(holding["shares"]))
    gross_brl = gross_per_share * shares
    rate = Decimal(str(fx["rate"]))
    amount_nok = gross_brl * rate
    movement_type = "BEMOBI_JCP" if action["action_type"] == "JCP" else "BEMOBI_DIVIDEND"
    description = (
        f"Confirmed Bemobi {action['action_type']} receipt: {int(shares)} shares x "
        f"BRL {decimal_text(gross_per_share)} gross per share. "
        "Booked on the confirmed payment date; JCP withholding is stored separately."
    )
    existing = await repository.first(
        "SELECT id FROM cash_movements WHERE corporate_action_id=? LIMIT 1",
        (int(action["id"]),),
    )
    values = (
        str(action["payment_date"]),
        movement_type,
        decimal_text(amount_nok),
        decimal_text(gross_brl),
        "BRL",
        decimal_text(rate),
        description,
        action.get("source_document_id"),
        "ESTIMATED",
        int(action["id"]),
    )
    if existing is None:
        await repository.run(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, amount_original,
                currency, fx_rate_to_nok, description, source_document_id,
                confidence, corporate_action_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        return "written"

    await repository.run(
        """
        UPDATE cash_movements
        SET movement_date=?, movement_type=?, amount_nok=?, amount_original=?,
            currency=?, fx_rate_to_nok=?, description=?, source_document_id=?,
            confidence=?
        WHERE corporate_action_id=?
        """,
        values,
    )
    return "updated"


async def _upsert_withholding(
    repository,
    *,
    action: dict[str, Any],
    holding: dict[str, Any],
    fx: dict[str, Any],
) -> str | None:
    if action["action_type"] != "JCP":
        return None
    tax = _tax_per_share(action)
    if tax is None:
        return None

    tax_per_share, basis = tax
    shares = Decimal(int(holding["shares"]))
    tax_brl = -(tax_per_share * shares)
    rate = Decimal(str(fx["rate"]))
    amount_nok = tax_brl * rate
    external_action_id = str(action.get("external_action_id") or f"action-{action['id']}")
    external_movement_id = f"bemobi-withholding:{external_action_id}"
    description = (
        f"Bemobi JCP withholding adjustment ({basis}): {int(shares)} shares x "
        f"BRL {decimal_text(tax_per_share)} tax per share. "
        "Stored separately so the confirmed distribution moves from receivable to net cash "
        "without changing NAV merely because the payment date is reached."
    )
    existing = await repository.first(
        "SELECT id FROM cash_movements WHERE external_movement_id=? LIMIT 1",
        (external_movement_id,),
    )
    values = (
        str(action["payment_date"]),
        "TAX",
        decimal_text(amount_nok),
        decimal_text(tax_brl),
        "BRL",
        decimal_text(rate),
        description,
        action.get("source_document_id"),
        "ESTIMATED",
        external_movement_id,
    )
    if existing is None:
        await repository.run(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, amount_original,
                currency, fx_rate_to_nok, description, source_document_id,
                confidence, external_movement_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        return "written"

    await repository.run(
        """
        UPDATE cash_movements
        SET movement_date=?, movement_type=?, amount_nok=?, amount_original=?,
            currency=?, fx_rate_to_nok=?, description=?, source_document_id=?,
            confidence=?
        WHERE external_movement_id=?
        """,
        values,
    )
    return "updated"


async def sync_confirmed_bemobi_distribution_cash(
    repository,
    *,
    target_date: str,
) -> dict[str, Any]:
    """Move confirmed Bemobi entitlements into cash on their payment date.

    Corporate actions remain the source of truth for the receivable lifecycle. This step
    only materializes payment-date cash rows, so ex-date <= day < payment-date stays a
    receivable and day >= payment-date becomes cash. The gross receipt and documented JCP
    withholding are kept separately for auditability; together they equal net cash.
    """
    actions = await repository.all(
        """
        SELECT ca.id, ca.external_action_id, ca.action_type, ca.ex_date,
               ca.payment_date, ca.amount_per_share, ca.net_amount_per_share,
               ca.withholding_rate, ca.tax_treatment, ca.source_document_id
        FROM corporate_actions ca
        JOIN instruments i ON i.id = ca.issuer_instrument_id
        WHERE i.symbol='BMOB3'
          AND ca.action_type IN ('DIVIDEND', 'JCP')
          AND ca.ex_date IS NOT NULL
          AND ca.payment_date IS NOT NULL
          AND ca.amount_per_share IS NOT NULL
          AND ca.payment_date <= ?
        ORDER BY ca.payment_date, ca.id
        """,
        (target_date,),
    )

    written = 0
    updated = 0
    skipped: list[dict[str, Any]] = []
    processed = 0
    for action in actions:
        entitlement_date = str(action["ex_date"])
        payment_date = str(action["payment_date"])
        holding = await _holding(repository, entitlement_date)
        fx = await _nearest_brl_nok(repository, payment_date)
        if holding is None or fx is None:
            skipped.append(
                {
                    "corporate_action_id": int(action["id"]),
                    "external_action_id": action.get("external_action_id"),
                    "payment_date": payment_date,
                    "reason": "missing_holding" if holding is None else "missing_brl_nok",
                }
            )
            continue

        receipt_result = await _upsert_receipt(
            repository,
            action=action,
            holding=holding,
            fx=fx,
        )
        written += int(receipt_result == "written")
        updated += int(receipt_result == "updated")

        tax_result = await _upsert_withholding(
            repository,
            action=action,
            holding=holding,
            fx=fx,
        )
        written += int(tax_result == "written")
        updated += int(tax_result == "updated")
        processed += 1

    return {
        "status": "partial" if skipped else "ok",
        "target_date": target_date,
        "actions_due": len(actions),
        "actions_processed": processed,
        "rows_written": written,
        "rows_updated": updated,
        "skipped": skipped,
        "policy": "confirmed-ex-date-receivable-to-payment-date-net-cash",
    }

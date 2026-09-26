from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

try:
    from .option_liability import decimal_text
except ImportError:
    from option_liability import decimal_text

MAX_FX_LOOKBACK_DAYS = 7


def _tax_per_share(action: dict[str, Any]) -> tuple[Decimal, str] | None:
    gross = Decimal(str(action["amount_per_share"]))
    if action.get("net_amount_per_share") is not None:
        tax = gross - Decimal(str(action["net_amount_per_share"]))
        return (tax, "PUBLISHED_NET") if tax > 0 else None
    if action.get("withholding_rate") is not None:
        tax = gross * Decimal(str(action["withholding_rate"]))
        return (tax, "PUBLISHED_WITHHOLDING_RATE") if tax > 0 else None
    return None


def _row_matches(existing: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in expected.items():
        current = existing.get(key)
        if value is None:
            if current is not None:
                return False
        elif str(current) != str(value):
            return False
    return True


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
    movement_type = (
        "BEMOBI_JCP" if action["action_type"] == "JCP" else "BEMOBI_DIVIDEND"
    )
    description = (
        f"Confirmed Bemobi {action['action_type']} receipt: {int(shares)} shares x "
        f"BRL {decimal_text(gross_per_share)} gross per share. "
        "Booked on the confirmed payment date; JCP withholding is stored separately."
    )
    expected = {
        "movement_date": str(action["payment_date"]),
        "movement_type": movement_type,
        "amount_nok": decimal_text(amount_nok),
        "amount_original": decimal_text(gross_brl),
        "currency": "BRL",
        "fx_rate_to_nok": decimal_text(rate),
        "description": description,
        "source_document_id": action.get("source_document_id"),
        "confidence": "ESTIMATED",
    }
    existing = await repository.first(
        """
        SELECT id, movement_date, movement_type, amount_nok, amount_original,
               currency, fx_rate_to_nok, description, source_document_id, confidence
        FROM cash_movements
        WHERE corporate_action_id=?
        LIMIT 1
        """,
        (int(action["id"]),),
    )
    values = (
        expected["movement_date"],
        expected["movement_type"],
        expected["amount_nok"],
        expected["amount_original"],
        expected["currency"],
        expected["fx_rate_to_nok"],
        expected["description"],
        expected["source_document_id"],
        expected["confidence"],
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
    if _row_matches(existing, expected):
        return "unchanged"

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
    external_action_id = str(
        action.get("external_action_id") or f"action-{action['id']}"
    )
    external_movement_id = f"bemobi-withholding:{external_action_id}"
    description = (
        f"Bemobi JCP withholding adjustment ({basis}): {int(shares)} shares x "
        f"BRL {decimal_text(tax_per_share)} tax per share. "
        "Stored separately so the confirmed distribution moves from receivable to net cash "
        "without changing NAV merely because the payment date is reached."
    )
    expected = {
        "movement_date": str(action["payment_date"]),
        "movement_type": "TAX",
        "amount_nok": decimal_text(amount_nok),
        "amount_original": decimal_text(tax_brl),
        "currency": "BRL",
        "fx_rate_to_nok": decimal_text(rate),
        "description": description,
        "source_document_id": action.get("source_document_id"),
        "confidence": "ESTIMATED",
    }
    existing = await repository.first(
        """
        SELECT id, movement_date, movement_type, amount_nok, amount_original,
               currency, fx_rate_to_nok, description, source_document_id, confidence
        FROM cash_movements
        WHERE external_movement_id=?
        LIMIT 1
        """,
        (external_movement_id,),
    )
    values = (
        expected["movement_date"],
        expected["movement_type"],
        expected["amount_nok"],
        expected["amount_original"],
        expected["currency"],
        expected["fx_rate_to_nok"],
        expected["description"],
        expected["source_document_id"],
        expected["confidence"],
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
    if _row_matches(existing, expected):
        return "unchanged"

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
               ca.payment_date,
               COALESCE(ca.gross_amount_per_share, ca.amount_per_share)
                   AS amount_per_share,
               ca.net_amount_per_share,
               ca.withholding_rate, ca.tax_treatment, ca.source_document_id,
               h.id AS holding_id, h.shares AS holding_shares,
               h.effective_from AS holding_effective_from,
               h.effective_to AS holding_effective_to,
               fr.id AS fx_id, substr(fr.observed_at, 1, 10) AS fx_rate_date,
               fr.rate AS fx_rate, fr.source_document_id AS fx_source_document_id,
               fs.code AS fx_source_code
        FROM corporate_actions ca
        JOIN instruments i ON i.id = ca.issuer_instrument_id
        LEFT JOIN bemobi_holdings h ON h.id = (
            SELECT candidate.id
            FROM bemobi_holdings candidate
            WHERE candidate.effective_from <= ca.ex_date
              AND (candidate.effective_to IS NULL OR candidate.effective_to >= ca.ex_date)
            ORDER BY candidate.effective_from DESC, candidate.id DESC
            LIMIT 1
        )
        LEFT JOIN fx_rates fr ON fr.id = (
            SELECT candidate.id
            FROM fx_rates candidate
            JOIN sources candidate_source ON candidate_source.id = candidate.source_id
            WHERE candidate.base_currency = 'BRL'
              AND candidate.quote_currency = 'NOK'
              AND substr(candidate.observed_at, 1, 10) <= ca.payment_date
              AND substr(candidate.observed_at, 1, 10) >=
                  date(ca.payment_date, '-' || ? || ' days')
            ORDER BY substr(candidate.observed_at, 1, 10) DESC,
                     CASE candidate_source.code
                       WHEN 'NORGES_BANK' THEN 0
                       WHEN 'ECB' THEN 1
                       ELSE 5
                     END,
                     candidate.observed_at DESC,
                     candidate.id DESC
            LIMIT 1
        )
        LEFT JOIN sources fs ON fs.id = fr.source_id
        WHERE i.symbol='BMOB3'
          AND ca.action_type IN ('DIVIDEND', 'JCP')
          AND ca.ex_date IS NOT NULL
          AND ca.payment_date IS NOT NULL
          AND COALESCE(ca.gross_amount_per_share, ca.amount_per_share) IS NOT NULL
          AND ca.payment_date <= ?
        ORDER BY ca.payment_date, ca.id
        """,
        (MAX_FX_LOOKBACK_DAYS, target_date),
    )

    written = 0
    updated = 0
    unchanged = 0
    skipped: list[dict[str, Any]] = []
    processed = 0
    for action in actions:
        payment_date = str(action["payment_date"])
        date.fromisoformat(payment_date)
        holding = (
            {
                "id": action["holding_id"],
                "shares": action["holding_shares"],
                "effective_from": action["holding_effective_from"],
                "effective_to": action["holding_effective_to"],
            }
            if action.get("holding_id") is not None
            else None
        )
        fx = (
            {
                "id": action["fx_id"],
                "rate_date": action["fx_rate_date"],
                "rate": action["fx_rate"],
                "source_document_id": action["fx_source_document_id"],
                "source_code": action["fx_source_code"],
            }
            if action.get("fx_id") is not None
            else None
        )
        if holding is None or fx is None:
            skipped.append(
                {
                    "corporate_action_id": int(action["id"]),
                    "external_action_id": action.get("external_action_id"),
                    "payment_date": payment_date,
                    "reason": (
                        "missing_holding" if holding is None else "missing_brl_nok"
                    ),
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
        unchanged += int(receipt_result == "unchanged")

        tax_result = await _upsert_withholding(
            repository,
            action=action,
            holding=holding,
            fx=fx,
        )
        written += int(tax_result == "written")
        updated += int(tax_result == "updated")
        unchanged += int(tax_result == "unchanged")
        processed += 1

    return {
        "status": "partial" if skipped else "ok",
        "target_date": target_date,
        "actions_due": len(actions),
        "actions_processed": processed,
        "rows_written": written,
        "rows_updated": updated,
        "rows_unchanged": unchanged,
        "skipped": skipped,
        "policy": "confirmed-ex-date-receivable-to-payment-date-net-cash",
    }

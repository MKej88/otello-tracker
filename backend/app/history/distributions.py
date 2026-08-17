from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, decimal_text, instrument_id

DATA_PATH = Path(__file__).with_name("data") / "bemobi_distributions.json"
MAX_FX_LOOKBACK_DAYS = 7


def load_bemobi_distributions() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _provenance_once(
    connection,
    *,
    entity_id: int,
    field_name: str,
    document_id: int,
    locator: str | None,
    value: str,
) -> None:
    # Curated manifests can be refined when a notice reveals more precise values.
    # Keep only the current value for the same field/document instead of accumulating
    # stale provenance rows that could look like conflicting source facts.
    connection.execute(
        """
        DELETE FROM provenance_records
        WHERE entity_table = 'corporate_actions' AND entity_id = ?
          AND field_name = ? AND source_document_id = ?
          AND COALESCE(extracted_value, '') <> ?
        """,
        (entity_id, field_name, document_id, value),
    )
    exists = connection.execute(
        """
        SELECT id FROM provenance_records
        WHERE entity_table = 'corporate_actions' AND entity_id = ?
          AND field_name = ? AND source_document_id = ?
          AND COALESCE(extracted_value, '') = ?
        LIMIT 1
        """,
        (entity_id, field_name, document_id, value),
    ).fetchone()
    if exists is not None:
        return
    connection.execute(
        """
        INSERT INTO provenance_records(
            entity_table, entity_id, field_name, source_document_id,
            source_locator, extraction_method, confidence, extracted_value
        ) VALUES ('corporate_actions', ?, ?, ?, ?, 'MANUAL', 'HIGH', ?)
        """,
        (entity_id, field_name, document_id, locator, value),
    )


def _existing_action(connection, issuer_id: int, document_id: int, item: dict[str, Any]):
    external_action_id = item["external_action_id"]
    row = connection.execute(
        """
        SELECT id, source_document_id FROM corporate_actions
        WHERE external_action_id = ? LIMIT 1
        """,
        (external_action_id,),
    ).fetchone()
    if row is not None:
        return row

    # First prefer an unclaimed legacy row from the same document.
    row = connection.execute(
        """
        SELECT id, source_document_id FROM corporate_actions
        WHERE issuer_instrument_id = ? AND source_document_id = ?
          AND external_action_id IS NULL
        ORDER BY id LIMIT 1
        """,
        (issuer_id, document_id),
    ).fetchone()
    if row is not None:
        return row

    # Phase 10 may replace an old curated IR-page document with a more precise official
    # shareholder notice. Match the old aggregate action by entitlement/payment dates so
    # an existing production DB is upgraded in place rather than retaining both versions.
    return connection.execute(
        """
        SELECT id, source_document_id FROM corporate_actions
        WHERE issuer_instrument_id = ? AND external_action_id IS NULL
          AND COALESCE(ex_date, '') = COALESCE(?, '')
          AND COALESCE(payment_date, '') = COALESCE(?, '')
        ORDER BY id LIMIT 1
        """,
        (issuer_id, item.get("ex_date"), item.get("payment_date")),
    ).fetchone()


def _nearest_brl_nok(connection, payment_date: str):
    floor = (date.fromisoformat(payment_date) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT id, substr(observed_at, 1, 10) AS rate_date, rate
        FROM fx_rates
        WHERE base_currency = 'BRL' AND quote_currency = 'NOK'
          AND substr(observed_at, 1, 10) <= ?
          AND substr(observed_at, 1, 10) >= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1
        """,
        (payment_date, floor),
    ).fetchone()


def _holding(connection, entitlement_date: str):
    return connection.execute(
        """
        SELECT id, shares FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (entitlement_date, entitlement_date),
    ).fetchone()


def _sync_withholding_adjustments(connection) -> dict[str, int]:
    """Book JCP withholding as a separate negative cash movement when documented.

    The underlying BEMOBI_JCP cash movement stays gross, which is also the entitlement
    used by FULL NAV. A separate TAX movement makes the payment-date cash net while
    preserving both facts in the audit trail. Because Otello's shareholder-specific tax
    treatment can differ from the standard Bemobi notice treatment, the adjustment stays
    ESTIMATED until a reported Otello cash anchor reconciles it.
    """
    written = 0
    updated = 0
    active_ids: set[str] = set()
    actions = connection.execute(
        """
        SELECT ca.id, ca.external_action_id, ca.ex_date, ca.payment_date,
               ca.amount_per_share, ca.net_amount_per_share, ca.withholding_rate,
               ca.tax_treatment, ca.source_document_id
        FROM corporate_actions ca
        JOIN instruments i ON i.id = ca.issuer_instrument_id
        WHERE i.symbol = 'BMOB3' AND ca.action_type = 'JCP'
          AND ca.external_action_id IS NOT NULL
          AND ca.ex_date IS NOT NULL AND ca.payment_date IS NOT NULL
          AND ca.amount_per_share IS NOT NULL
        ORDER BY ca.payment_date, ca.id
        """
    ).fetchall()

    for action in actions:
        gross_per_share = Decimal(action["amount_per_share"])
        basis: str | None = None
        if action["net_amount_per_share"] is not None:
            tax_per_share = gross_per_share - Decimal(action["net_amount_per_share"])
            basis = "PUBLISHED_NET"
        elif action["withholding_rate"] is not None:
            tax_per_share = gross_per_share * Decimal(action["withholding_rate"])
            basis = "STANDARD_WITHHOLDING"
        else:
            continue
        if tax_per_share <= 0:
            continue

        holding = _holding(connection, action["ex_date"])
        fx = _nearest_brl_nok(connection, action["payment_date"])
        if holding is None or fx is None:
            continue

        external_movement_id = f"bemobi-withholding:{action['external_action_id']}"
        active_ids.add(external_movement_id)
        amount_original = -(tax_per_share * Decimal(holding["shares"]))
        fx_rate = Decimal(fx["rate"])
        amount_nok = amount_original * fx_rate
        rate_text = action["withholding_rate"] or "derived-from-published-net"
        description = (
            f"Bemobi JCP withholding adjustment ({basis}): {holding['shares']} shares x "
            f"BRL {decimal_text(tax_per_share)} tax per share; notice rate {rate_text}. "
            "Booked separately from gross JCP; shareholder-specific treatment may differ "
            "and is reconciled to the next reported Otello cash anchor."
        )
        existing = connection.execute(
            "SELECT id FROM cash_movements WHERE external_movement_id = ?",
            (external_movement_id,),
        ).fetchone()
        values = (
            action["payment_date"],
            "TAX",
            decimal_text(amount_nok),
            decimal_text(amount_original),
            "BRL",
            decimal_text(fx_rate),
            description,
            action["source_document_id"],
            "ESTIMATED",
            external_movement_id,
        )
        if existing is None:
            connection.execute(
                """
                INSERT INTO cash_movements(
                    movement_date, movement_type, amount_nok, amount_original,
                    currency, fx_rate_to_nok, description, source_document_id,
                    confidence, external_movement_id
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
                WHERE external_movement_id = ?
                """,
                values,
            )
            updated += 1

    # If a future manifest correction removes a previously assumed tax treatment, remove
    # only Phase-10 generated adjustments; never touch unrelated TAX movements.
    stale = [
        row["external_movement_id"]
        for row in connection.execute(
            """
            SELECT external_movement_id FROM cash_movements
            WHERE external_movement_id LIKE 'bemobi-withholding:%'
            """
        ).fetchall()
        if row["external_movement_id"] not in active_ids
    ]
    for external_movement_id in stale:
        connection.execute(
            "DELETE FROM cash_movements WHERE external_movement_id = ?",
            (external_movement_id,),
        )

    return {"written": written, "updated": updated, "deleted": len(stale)}


def seed_bemobi_distributions(database_path: str | None = None) -> dict[str, Any]:
    """Seed official Bemobi distribution components used by FULL NAV and cash.

    ``amount_per_share`` and ``total_amount`` remain the canonical gross values for
    backward compatibility. Phase 10 additionally stores published/derived net values,
    withholding rates and component groups. FULL NAV receivables continue to use gross
    entitlements. Payment-date JCP withholding is represented as a separate TAX movement.
    """
    data = load_bemobi_distributions()
    written = 0
    updated = 0
    with get_connection(database_path) as connection:
        documents: dict[str, int] = {}
        for item in data["documents"]:
            documents[item["key"]] = create_source_document(
                connection,
                source_code=item["source_code"],
                external_id=item["external_id"],
                document_type=item["document_type"],
                title=item["title"],
                url=item["url"],
                published_at=item.get("published_at"),
                metadata={"curated": True, "distribution_manifest": data["version"]},
            )

        issuer_id = instrument_id(connection, "BMOB3")
        for item in data["corporate_actions"]:
            document_id = documents[item["source_key"]]
            row = _existing_action(connection, issuer_id, document_id, item)

            gross_per_share = item.get("gross_amount_per_share", item.get("amount_per_share"))
            gross_total = item.get("gross_total_amount", item.get("total_amount"))
            values = (
                item["action_type"],
                item.get("announcement_date"),
                item.get("ex_date"),
                item.get("record_date"),
                item.get("payment_date"),
                gross_per_share,
                gross_total,
                item.get("currency"),
                document_id,
                item.get("notes"),
                item["external_action_id"],
                gross_per_share,
                item.get("net_amount_per_share"),
                gross_total,
                item.get("net_total_amount"),
                item.get("withholding_rate"),
                item.get("tax_treatment"),
                item.get("component_group"),
            )
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO corporate_actions(
                        issuer_instrument_id, action_type, announcement_date, ex_date,
                        record_date, payment_date, amount_per_share, total_amount,
                        currency, source_document_id, notes, external_action_id,
                        gross_amount_per_share, net_amount_per_share, gross_total_amount,
                        net_total_amount, withholding_rate, tax_treatment, component_group
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (issuer_id, *values),
                )
                action_id = int(cursor.lastrowid)
                written += 1
            else:
                action_id = int(row["id"])
                previous_document_id = int(row["source_document_id"])
                if previous_document_id != document_id:
                    connection.execute(
                        """
                        DELETE FROM provenance_records
                        WHERE entity_table = 'corporate_actions' AND entity_id = ?
                          AND source_document_id = ?
                        """,
                        (action_id, previous_document_id),
                    )
                connection.execute(
                    """
                    UPDATE corporate_actions
                    SET action_type = ?, announcement_date = ?, ex_date = ?, record_date = ?,
                        payment_date = ?, amount_per_share = ?, total_amount = ?, currency = ?,
                        source_document_id = ?, notes = ?, external_action_id = ?,
                        gross_amount_per_share = ?, net_amount_per_share = ?,
                        gross_total_amount = ?, net_total_amount = ?, withholding_rate = ?,
                        tax_treatment = ?, component_group = ?
                    WHERE id = ?
                    """,
                    (*values, action_id),
                )
                updated += 1

            provenance_fields = {
                "action_type": item["action_type"],
                "ex_date": item.get("ex_date"),
                "payment_date": item.get("payment_date"),
                "amount_per_share": gross_per_share,
                "total_amount": gross_total,
                "net_amount_per_share": item.get("net_amount_per_share"),
                "net_total_amount": item.get("net_total_amount"),
                "withholding_rate": item.get("withholding_rate"),
                "currency": item.get("currency"),
            }
            for field_name, field_value in provenance_fields.items():
                if field_value is not None:
                    _provenance_once(
                        connection,
                        entity_id=action_id,
                        field_name=field_name,
                        document_id=document_id,
                        locator=item.get("source_locator"),
                        value=str(field_value),
                    )

        withholding = _sync_withholding_adjustments(connection)
        connection.commit()
    return {
        "manifest_version": data["version"],
        "written": written,
        "updated": updated,
        "count": len(data["corporate_actions"]),
        "withholding_adjustments": withholding,
    }

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, instrument_id

DATA_PATH = Path(__file__).with_name("data") / "bemobi_distributions.json"


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
        "SELECT id FROM corporate_actions WHERE external_action_id = ? LIMIT 1",
        (external_action_id,),
    ).fetchone()
    if row is not None:
        return row

    # Phase 10 upgrades older aggregate rows in place. Claim one legacy row from the
    # same official document before inserting extra components, preserving any FK from
    # cash_movements and avoiding stale duplicate actions after an upgrade.
    return connection.execute(
        """
        SELECT id FROM corporate_actions
        WHERE issuer_instrument_id = ? AND source_document_id = ?
          AND external_action_id IS NULL
        ORDER BY id LIMIT 1
        """,
        (issuer_id, document_id),
    ).fetchone()


def seed_bemobi_distributions(database_path: str | None = None) -> dict[str, Any]:
    """Seed official Bemobi distribution components used by FULL NAV and cash.

    ``amount_per_share`` and ``total_amount`` remain the canonical gross values for
    backward compatibility. Phase 10 additionally stores published/derived net values,
    withholding rates and component groups. FULL NAV receivables continue to use gross
    entitlements; payment-date cash may use a notice-supported net amount for JCP.

    Cash derived for Otello remains ESTIMATED until reconciled to a reported Otello cash
    anchor because shareholder-specific tax treatment can differ from Bemobi's standard
    notice treatment.
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
                    (issuer_id, *values[:8], document_id, *values[8:]),
                )
                action_id = int(cursor.lastrowid)
                written += 1
            else:
                action_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE corporate_actions
                    SET action_type = ?, announcement_date = ?, ex_date = ?, record_date = ?,
                        payment_date = ?, amount_per_share = ?, total_amount = ?, currency = ?,
                        notes = ?, external_action_id = ?, gross_amount_per_share = ?,
                        net_amount_per_share = ?, gross_total_amount = ?, net_total_amount = ?,
                        withholding_rate = ?, tax_treatment = ?, component_group = ?
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

        connection.commit()
    return {
        "manifest_version": data["version"],
        "written": written,
        "updated": updated,
        "count": len(data["corporate_actions"]),
    }

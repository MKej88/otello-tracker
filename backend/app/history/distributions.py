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


def seed_bemobi_distributions(database_path: str | None = None) -> dict[str, Any]:
    """Seed the official Bemobi distribution history used by the cash curve.

    The corporate-action facts are confirmed. Cash received by Otello is derived later
    from Otello's eligible BMOB3 holding and payment-date BRL/NOK. JCP/mixed distributions
    can have withholding, so the resulting cash movement is intentionally marked estimated
    until it is reconciled to the next reported Otello cash anchor.
    """
    data = load_bemobi_distributions()
    written = 0
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
            row = connection.execute(
                """
                SELECT id FROM corporate_actions
                WHERE issuer_instrument_id = ? AND action_type = ?
                  AND source_document_id = ?
                LIMIT 1
                """,
                (issuer_id, item["action_type"], document_id),
            ).fetchone()
            values = (
                item.get("announcement_date"),
                item.get("ex_date"),
                item.get("record_date"),
                item.get("payment_date"),
                item.get("amount_per_share"),
                item.get("total_amount"),
                item.get("currency"),
                item.get("notes"),
            )
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO corporate_actions(
                        issuer_instrument_id, action_type, announcement_date, ex_date,
                        record_date, payment_date, amount_per_share, total_amount,
                        currency, source_document_id, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (issuer_id, item["action_type"], *values[:7], document_id, values[7]),
                )
                action_id = int(cursor.lastrowid)
                written += 1
            else:
                action_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE corporate_actions
                    SET announcement_date = ?, ex_date = ?, record_date = ?, payment_date = ?,
                        amount_per_share = ?, total_amount = ?, currency = ?, notes = ?
                    WHERE id = ?
                    """,
                    (*values, action_id),
                )

            for field_name in ("ex_date", "payment_date", "amount_per_share", "total_amount", "currency"):
                if item.get(field_name) is not None:
                    _provenance_once(
                        connection,
                        entity_id=action_id,
                        field_name=field_name,
                        document_id=document_id,
                        locator=item.get("source_locator"),
                        value=str(item[field_name]),
                    )

        connection.commit()
    return {"manifest_version": data["version"], "written": written, "count": len(data["corporate_actions"])}

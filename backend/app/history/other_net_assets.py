from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, decimal_text

DATA_PATH = Path(__file__).with_name("data") / "other_net_assets_anchors.json"


def load_other_net_assets_manifest() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _provenance_once(
    connection,
    *,
    entity_id: int,
    field_name: str,
    source_document_id: int,
    source_locator: str | None,
    extracted_value: str,
) -> None:
    row = connection.execute(
        """
        SELECT id FROM provenance_records
        WHERE entity_table = 'other_net_assets_reported_anchors'
          AND entity_id = ? AND field_name = ? AND source_document_id = ?
          AND COALESCE(source_locator, '') = COALESCE(?, '')
          AND COALESCE(extracted_value, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (entity_id, field_name, source_document_id, source_locator, extracted_value),
    ).fetchone()
    if row is not None:
        return
    connection.execute(
        """
        INSERT INTO provenance_records(
            entity_table, entity_id, field_name, source_document_id,
            source_locator, extraction_method, confidence, extracted_value
        ) VALUES ('other_net_assets_reported_anchors', ?, ?, ?, ?, 'MANUAL', ?, ?)
        """,
        (
            entity_id,
            field_name,
            source_document_id,
            source_locator,
            "MEDIUM" if field_name == "other_net_assets_reported" and extracted_value == "1400000" else "HIGH",
            extracted_value,
        ),
    )


def seed_other_net_assets_reported(database_path: str | None = None) -> dict[str, Any]:
    manifest = load_other_net_assets_manifest()
    written = 0
    with get_connection(database_path) as connection:
        documents: dict[str, int] = {}
        for item in manifest["documents"]:
            documents[item["key"]] = create_source_document(
                connection,
                source_code=item["source_code"],
                external_id=item["external_id"],
                document_type=item["document_type"],
                title=item["title"],
                url=item["url"],
                metadata={
                    "full_nav_manifest_version": manifest["version"],
                    "curated": True,
                    "extraction_method_detail": "MANUAL_CURATED_REPORT",
                },
            )

        for item in manifest["anchors"]:
            total_assets = Decimal(item["total_assets"])
            cash = Decimal(item["cash"])
            bemobi = Decimal(item["bemobi_carrying"])
            liabilities = Decimal(item["total_liabilities"])
            declared = Decimal(item["other_net_assets"])
            calculated = total_assets - cash - bemobi - liabilities
            if calculated != declared:
                raise ValueError(
                    f"ONA anchor {item['as_of_date']} does not reconcile: "
                    f"calculated {calculated}, declared {declared}"
                )

            document_id = documents[item["source_key"]]
            row = connection.execute(
                """
                SELECT id FROM other_net_assets_reported_anchors
                WHERE as_of_date = ? AND source_document_id = ?
                """,
                (item["as_of_date"], document_id),
            ).fetchone()
            values = (
                decimal_text(total_assets),
                decimal_text(cash),
                decimal_text(bemobi),
                decimal_text(liabilities),
                manifest.get("currency", "USD"),
                decimal_text(declared),
                item["precision_status"],
                1 if item.get("restated") else 0,
                item.get("source_locator"),
                item.get("notes"),
            )
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO other_net_assets_reported_anchors(
                        as_of_date, total_assets_reported, cash_reported,
                        bemobi_carrying_reported, total_liabilities_reported,
                        reported_currency, other_net_assets_reported,
                        precision_status, restated, source_document_id,
                        source_locator, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (item["as_of_date"], *values[:8], document_id, *values[8:]),
                )
                entity_id = int(cursor.lastrowid)
                written += 1
            else:
                entity_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE other_net_assets_reported_anchors
                    SET total_assets_reported = ?, cash_reported = ?,
                        bemobi_carrying_reported = ?, total_liabilities_reported = ?,
                        reported_currency = ?, other_net_assets_reported = ?,
                        precision_status = ?, restated = ?, source_locator = ?, notes = ?
                    WHERE id = ?
                    """,
                    (*values, entity_id),
                )

            field_values = {
                "total_assets_reported": total_assets,
                "cash_reported": cash,
                "bemobi_carrying_reported": bemobi,
                "total_liabilities_reported": liabilities,
                "other_net_assets_reported": declared,
            }
            for field_name, value in field_values.items():
                _provenance_once(
                    connection,
                    entity_id=entity_id,
                    field_name=field_name,
                    source_document_id=document_id,
                    source_locator=item.get("source_locator"),
                    extracted_value=decimal_text(value),
                )

        connection.commit()

    return {
        "manifest_version": manifest["version"],
        "written": written,
        "anchors": len(manifest["anchors"]),
        "from": manifest["anchors"][0]["as_of_date"],
        "to": manifest["anchors"][-1]["as_of_date"],
        "known_gaps": manifest.get("known_gaps", []),
    }

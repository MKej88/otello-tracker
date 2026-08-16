from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, instrument_id

DATA_DIR = Path(__file__).with_name("data")
MANIFEST_PATH = DATA_DIR / "otello_report_anchors.json"
CORRECTIONS_PATH = DATA_DIR / "otello_2021_corrections.json"


def load_manifest() -> dict[str, Any]:
    """Load the base history plus later evidence-backed corrections.

    Keeping corrections in a separate overlay makes revisions reviewable instead of
    silently rewriting the original curated dataset.
    """
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    corrections = json.loads(CORRECTIONS_PATH.read_text(encoding="utf-8"))

    manifest["version"] = corrections["version"]
    manifest["documents"] = manifest["documents"] + corrections.get("documents", [])
    manifest["share_counts"] = manifest["share_counts"] + corrections.get("share_counts", [])

    # The original Phase 3 Bemobi holding deliberately started in 2022 because the
    # greenshoe effective date was then unresolved. The correction overlay replaces
    # that conservative range with the exact IPO/greenshoe history.
    manifest["bemobi_holdings"] = corrections.get(
        "bemobi_holdings", manifest["bemobi_holdings"]
    )

    # Two Phase 3 cancellation quantities were correct in isolation but attached to
    # the wrong event dates. Remove those specific rows from the logical manifest and
    # replace them with the verified registration sequence.
    superseded_actions = {
        ("SHARE_CANCELLATION", "2021-09-30", 11200000),
        ("SHARE_CANCELLATION", "2022-01-27", 9999998),
    }
    manifest["corporate_actions"] = [
        item
        for item in manifest["corporate_actions"]
        if (
            item["action_type"],
            item.get("announcement_date"),
            item.get("quantity"),
        )
        not in superseded_actions
    ] + corrections.get("corporate_actions", [])

    resolved = set(corrections.get("resolved_gap_codes", []))
    manifest["known_gaps"] = [
        gap for gap in manifest.get("known_gaps", []) if gap["code"] not in resolved
    ]
    return manifest


def _record_provenance_once(
    connection,
    *,
    entity_table: str,
    entity_id: int,
    field_name: str,
    source_document_id: int,
    source_locator: str | None,
    confidence: str,
    extracted_value: str | None,
) -> None:
    existing = connection.execute(
        """
        SELECT id FROM provenance_records
        WHERE entity_table = ? AND entity_id = ? AND field_name = ?
          AND source_document_id = ?
          AND COALESCE(source_locator, '') = COALESCE(?, '')
          AND COALESCE(extracted_value, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (
            entity_table,
            entity_id,
            field_name,
            source_document_id,
            source_locator,
            extracted_value,
        ),
    ).fetchone()
    if existing is not None:
        return

    connection.execute(
        """
        INSERT INTO provenance_records(
            entity_table, entity_id, field_name, source_document_id,
            source_locator, extraction_method, confidence, extracted_value
        ) VALUES (?, ?, ?, ?, ?, 'MANUAL', ?, ?)
        """,
        (
            entity_table,
            entity_id,
            field_name,
            source_document_id,
            source_locator,
            confidence,
            extracted_value,
        ),
    )


def _seed_documents(connection, manifest: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for document in manifest["documents"]:
        document_id = create_source_document(
            connection,
            source_code=document["source_code"],
            external_id=document["external_id"],
            document_type=document["document_type"],
            title=document["title"],
            url=document["url"],
            published_at=document.get("published_at"),
            metadata={
                "history_manifest_version": manifest["version"],
                "curated": True,
            },
        )
        result[document["key"]] = document_id
    return result


def _seed_cash(connection, manifest: dict[str, Any], documents: dict[str, int]) -> int:
    written = 0
    for item in manifest["cash_anchors"]:
        document_id = documents[item["source_key"]]
        row = connection.execute(
            """
            SELECT id FROM cash_anchors
            WHERE as_of_date = ? AND anchor_type = 'REPORTED' AND source_document_id = ?
            """,
            (item["as_of_date"], document_id),
        ).fetchone()

        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO cash_anchors(
                    as_of_date, amount_nok, reported_amount, reported_currency,
                    fx_rate_to_nok, anchor_type, source_document_id, notes
                ) VALUES (?, NULL, ?, ?, NULL, 'REPORTED', ?, ?)
                """,
                (
                    item["as_of_date"],
                    item["reported_amount"],
                    item["reported_currency"],
                    document_id,
                    item.get("notes"),
                ),
            )
            entity_id = int(cursor.lastrowid)
            written += 1
        else:
            entity_id = int(row["id"])
            connection.execute(
                """
                UPDATE cash_anchors
                SET amount_nok = NULL,
                    reported_amount = ?, reported_currency = ?, fx_rate_to_nok = NULL,
                    notes = ?
                WHERE id = ?
                """,
                (
                    item["reported_amount"],
                    item["reported_currency"],
                    item.get("notes"),
                    entity_id,
                ),
            )

        for field_name in ("reported_amount", "reported_currency"):
            _record_provenance_once(
                connection,
                entity_table="cash_anchors",
                entity_id=entity_id,
                field_name=field_name,
                source_document_id=document_id,
                source_locator=item.get("source_locator"),
                confidence=item["confidence"],
                extracted_value=str(item[field_name]),
            )
    return written


def _seed_share_counts(connection, manifest: dict[str, Any], documents: dict[str, int]) -> int:
    written = 0
    for item in manifest["share_counts"]:
        document_id = documents[item["source_key"]]
        row = connection.execute(
            """
            SELECT id FROM otello_share_counts
            WHERE effective_from = ? AND effective_to = ? AND source_document_id = ?
            """,
            (item["as_of_date"], item["as_of_date"], document_id),
        ).fetchone()

        values = (
            item["total_shares"],
            item["treasury_shares"],
            item["outstanding_shares"],
            item.get("notes"),
        )
        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO otello_share_counts(
                    effective_from, effective_to, total_shares, treasury_shares,
                    outstanding_shares, source_document_id, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["as_of_date"],
                    item["as_of_date"],
                    *values[:3],
                    document_id,
                    values[3],
                ),
            )
            entity_id = int(cursor.lastrowid)
            written += 1
        else:
            entity_id = int(row["id"])
            connection.execute(
                """
                UPDATE otello_share_counts
                SET total_shares = ?, treasury_shares = ?, outstanding_shares = ?, notes = ?
                WHERE id = ?
                """,
                (*values, entity_id),
            )

        for field_name in ("total_shares", "treasury_shares", "outstanding_shares"):
            _record_provenance_once(
                connection,
                entity_table="otello_share_counts",
                entity_id=entity_id,
                field_name=field_name,
                source_document_id=document_id,
                source_locator=item.get("source_locator"),
                confidence=item["confidence"],
                extracted_value=str(item[field_name]),
            )
    return written


def _seed_bemobi_holdings(connection, manifest: dict[str, Any], documents: dict[str, int]) -> int:
    written = 0
    for item in manifest["bemobi_holdings"]:
        document_id = documents[item["source_key"]]
        row = connection.execute(
            """
            SELECT id FROM bemobi_holdings
            WHERE effective_from = ? AND source_document_id = ?
            """,
            (item["effective_from"], document_id),
        ).fetchone()

        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO bemobi_holdings(
                    effective_from, effective_to, shares, ownership_pct,
                    source_document_id, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["effective_from"],
                    item.get("effective_to"),
                    item["shares"],
                    item.get("ownership_pct"),
                    document_id,
                    item.get("notes"),
                ),
            )
            entity_id = int(cursor.lastrowid)
            written += 1
        else:
            entity_id = int(row["id"])
            connection.execute(
                """
                UPDATE bemobi_holdings
                SET effective_to = ?, shares = ?, ownership_pct = ?, notes = ?
                WHERE id = ?
                """,
                (
                    item.get("effective_to"),
                    item["shares"],
                    item.get("ownership_pct"),
                    item.get("notes"),
                    entity_id,
                ),
            )

        for field_name in ("shares", "ownership_pct"):
            if item.get(field_name) is None:
                continue
            _record_provenance_once(
                connection,
                entity_table="bemobi_holdings",
                entity_id=entity_id,
                field_name=field_name,
                source_document_id=document_id,
                source_locator=item.get("source_locator"),
                confidence=item["confidence"],
                extracted_value=str(item[field_name]),
            )
    return written


def _seed_corporate_actions(connection, manifest: dict[str, Any], documents: dict[str, int]) -> int:
    written = 0
    for item in manifest["corporate_actions"]:
        document_id = documents[item["source_key"]]
        issuer_id = instrument_id(connection, item["symbol"])
        row = connection.execute(
            """
            SELECT id FROM corporate_actions
            WHERE issuer_instrument_id = ? AND action_type = ?
              AND COALESCE(announcement_date, '') = COALESCE(?, '')
              AND source_document_id = ?
            """,
            (issuer_id, item["action_type"], item.get("announcement_date"), document_id),
        ).fetchone()

        action_values = (
            item.get("announcement_date"),
            item.get("ex_date"),
            item.get("record_date"),
            item.get("payment_date"),
            item.get("amount_per_share"),
            item.get("total_amount"),
            item.get("currency"),
            item.get("quantity"),
            item.get("notes"),
        )
        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO corporate_actions(
                    issuer_instrument_id, action_type, announcement_date, ex_date,
                    record_date, payment_date, amount_per_share, total_amount,
                    currency, source_document_id, notes, quantity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issuer_id,
                    item["action_type"],
                    *action_values[:7],
                    document_id,
                    action_values[8],
                    action_values[7],
                ),
            )
            entity_id = int(cursor.lastrowid)
            written += 1
        else:
            entity_id = int(row["id"])
            connection.execute(
                """
                UPDATE corporate_actions
                SET announcement_date = ?, ex_date = ?, record_date = ?, payment_date = ?,
                    amount_per_share = ?, total_amount = ?, currency = ?, quantity = ?, notes = ?
                WHERE id = ?
                """,
                (*action_values, entity_id),
            )

        for field_name in (
            "announcement_date",
            "ex_date",
            "record_date",
            "payment_date",
            "amount_per_share",
            "total_amount",
            "currency",
            "quantity",
        ):
            if item.get(field_name) is None:
                continue
            _record_provenance_once(
                connection,
                entity_table="corporate_actions",
                entity_id=entity_id,
                field_name=field_name,
                source_document_id=document_id,
                source_locator=item.get("source_locator"),
                confidence=item["confidence"],
                extracted_value=str(item[field_name]),
            )
    return written


def seed_curated_history(database_path: str | None = None) -> dict[str, Any]:
    manifest = load_manifest()
    with get_connection(database_path) as connection:
        documents = _seed_documents(connection, manifest)
        result = {
            "manifest_version": manifest["version"],
            "documents": len(documents),
            "cash_anchors_written": _seed_cash(connection, manifest, documents),
            "share_counts_written": _seed_share_counts(connection, manifest, documents),
            "bemobi_holdings_written": _seed_bemobi_holdings(connection, manifest, documents),
            "corporate_actions_written": _seed_corporate_actions(connection, manifest, documents),
            "known_gaps": manifest["known_gaps"],
        }
        connection.commit()
        return result


def history_status(database_path: str | None = None) -> dict[str, Any]:
    manifest = load_manifest()
    with get_connection(database_path) as connection:
        cash = connection.execute(
            "SELECT COUNT(*) AS n, MIN(as_of_date) AS min_date, MAX(as_of_date) AS max_date FROM cash_anchors WHERE anchor_type = 'REPORTED'"
        ).fetchone()
        shares = connection.execute(
            "SELECT COUNT(*) AS n, MIN(effective_from) AS min_date, MAX(effective_from) AS max_date FROM otello_share_counts"
        ).fetchone()
        holding = connection.execute(
            "SELECT shares, ownership_pct, effective_from FROM bemobi_holdings ORDER BY effective_from DESC LIMIT 1"
        ).fetchone()
        actions = connection.execute("SELECT COUNT(*) AS n FROM corporate_actions").fetchone()

        return {
            "status": "ok",
            "manifest_version": manifest["version"],
            "cash_anchors": {
                "count": cash["n"],
                "from": cash["min_date"],
                "to": cash["max_date"],
            },
            "share_count_anchors": {
                "count": shares["n"],
                "from": shares["min_date"],
                "to": shares["max_date"],
            },
            "bemobi_holding": dict(holding) if holding is not None else None,
            "corporate_actions": actions["n"],
            "known_gaps": manifest["known_gaps"],
        }

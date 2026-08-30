from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document

DATA_PATH = Path(__file__).with_name("data") / "life360_holdings.json"


def load_life360_holdings_manifest() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _validate_holdings(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Life360 holdings manifest must contain at least one holding anchor")

    ordered = sorted(rows, key=lambda item: str(item["effective_from"]))
    previous_to: date | None = None
    previous_open_ended = False
    for index, item in enumerate(ordered):
        effective_from = date.fromisoformat(str(item["effective_from"]))
        effective_to_raw = item.get("effective_to")
        effective_to = None if effective_to_raw is None else date.fromisoformat(str(effective_to_raw))
        shares = int(item["shares"])
        if shares < 0:
            raise ValueError("Life360 holding shares cannot be negative")
        if effective_to is not None and effective_to < effective_from:
            raise ValueError("Life360 holding effective_to cannot precede effective_from")
        if index > 0:
            if previous_open_ended:
                raise ValueError("Open-ended Life360 holding must be the final anchor")
            if previous_to is not None and effective_from <= previous_to:
                raise ValueError("Life360 holding anchors cannot overlap")
        previous_to = effective_to
        previous_open_ended = effective_to is None


def _provenance_once(
    connection,
    *,
    entity_id: int,
    source_document_id: int,
    source_locator: str | None,
    shares: int,
    extraction_method: str,
    confidence: str,
) -> None:
    row = connection.execute(
        """
        SELECT id FROM provenance_records
        WHERE entity_table='life360_holding_anchors'
          AND entity_id=?
          AND field_name='shares'
          AND source_document_id=?
          AND COALESCE(source_locator, '')=COALESCE(?, '')
          AND COALESCE(extracted_value, '')=?
        LIMIT 1
        """,
        (entity_id, source_document_id, source_locator, str(shares)),
    ).fetchone()
    if row is not None:
        return
    connection.execute(
        """
        INSERT INTO provenance_records(
            entity_table, entity_id, field_name, source_document_id,
            source_locator, extraction_method, confidence, extracted_value
        ) VALUES ('life360_holding_anchors', ?, 'shares', ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            source_document_id,
            source_locator,
            extraction_method,
            confidence,
            str(shares),
        ),
    )


def seed_life360_holdings(database_path: str | None = None) -> dict[str, Any]:
    manifest = load_life360_holdings_manifest()
    rows = list(manifest["holdings"])
    _validate_holdings(rows)
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
                    "life360_holdings_manifest_version": manifest["version"],
                    "curated": True,
                },
            )

        for item in rows:
            document_id = documents[item["source_key"]]
            existing = connection.execute(
                "SELECT id FROM life360_holding_anchors WHERE effective_from=? LIMIT 1",
                (item["effective_from"],),
            ).fetchone()
            values = (
                item.get("effective_to"),
                int(item["shares"]),
                str(item["quality"]),
                str(item["basis"]),
                document_id,
                item.get("source_locator"),
                item.get("notes"),
            )
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO life360_holding_anchors(
                        effective_from, effective_to, shares, quality, basis,
                        source_document_id, source_locator, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (item["effective_from"], *values),
                )
                entity_id = int(cursor.lastrowid)
                written += 1
            else:
                entity_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE life360_holding_anchors
                    SET effective_to=?, shares=?, quality=?, basis=?, source_document_id=?,
                        source_locator=?, notes=?,
                        updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id=?
                    """,
                    (*values, entity_id),
                )

            quality = str(item["quality"])
            confidence = str(
                item.get("provenance_confidence")
                or ("MEDIUM" if "MEDIUM" in quality else "HIGH")
            )
            _provenance_once(
                connection,
                entity_id=entity_id,
                source_document_id=document_id,
                source_locator=item.get("source_locator"),
                shares=int(item["shares"]),
                extraction_method=str(item.get("extraction_method") or "CALCULATED"),
                confidence=confidence,
            )

        connection.commit()

    return {
        "manifest_version": manifest["version"],
        "written": written,
        "anchors": len(rows),
        "from": min(str(item["effective_from"]) for item in rows),
        "to": max(str(item["effective_from"]) for item in rows),
    }

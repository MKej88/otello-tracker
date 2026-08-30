from __future__ import annotations

import json
from pathlib import Path

from app.bemobi.source_status import bemobi_source_status
from app.db.connection import get_connection
from app.db.migration_runner import init_database


def _database(tmp_path: Path) -> str:
    database = str(tmp_path / "source-status.db")
    init_database(database)
    return database


def test_source_status_exposes_nested_full_refresh_results(tmp_path: Path) -> None:
    database = _database(tmp_path)
    metadata = {
        "phase": "16.2",
        "target_date": "2026-08-20",
        "result": {
            "ir": {"status": "ok", "rows_written": 5},
            "result_release": {
                "status": "skipped",
                "reason": "latest_result_already_ingested",
                "rows_written": 0,
            },
            "consensus": {
                "status": "not_available",
                "error": "MarketScreener svarte ikke",
                "rows_written": 0,
            },
            "xp_preview": {
                "status": "not_available",
                "reason": "no_public_preview_for_next_quarter",
                "rows_written": 0,
            },
        },
    }
    with get_connection(database) as connection:
        source_id = connection.execute(
            "SELECT id FROM sources WHERE code='BEMOBI_IR'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO source_health(source_id, checked_at, status, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (source_id, "2026-08-20T17:00:00Z", "DEGRADED", json.dumps(metadata)),
        )
        connection.commit()

    result = bemobi_source_status(database)
    by_key = {item["key"]: item for item in result["items"]}

    assert result["overall_status"] == "PARTIAL"
    assert result["checked_at"] == "2026-08-20T17:00:00Z"
    assert by_key["ir"]["status"] == "OK"
    assert by_key["result_release"]["status"] == "OK"
    assert by_key["consensus"]["status"] == "DEGRADED"
    assert by_key["consensus"]["uses_last_good"] is True
    assert by_key["xp_preview"]["status"] == "WAITING"


def test_source_status_is_unknown_before_first_new_full_refresh(tmp_path: Path) -> None:
    database = _database(tmp_path)

    result = bemobi_source_status(database)

    assert result["overall_status"] == "UNKNOWN"
    assert result["checked_at"] is None
    assert len(result["items"]) == 11
    assert all(item["status"] == "UNKNOWN" for item in result["items"])
    assert any(item["last_good_at"] is not None for item in result["items"])


def test_source_status_has_stable_source_order_and_labels(tmp_path: Path) -> None:
    database = _database(tmp_path)

    result = bemobi_source_status(database)

    assert [(item["key"], item["label"]) for item in result["items"]] == [
        ("norges_bank", "Valutakurser (BRL/NOK og USD/NOK)"),
        ("b3", "Bemobi-kurs og markedsdata"),
        ("euronext", "OTEC-kurs og handler"),
        ("yahoo_finance", "Life360-kurs"),
        ("newsweb", "Børsmeldinger og tilbakekjøp"),
        ("otello_ir", "Rapporter og selskapsinformasjon"),
        ("life360_ir", "Reservekilde for Life360-kurs"),
        ("ir", "Eierandel og analytikerdekning"),
        ("result_release", "Resultater"),
        ("consensus", "Årsestimater / konsensus"),
        ("xp_preview", "Forhåndsestimat neste kvartal"),
    ]


def test_source_status_does_not_turn_green_when_health_row_lacks_subresults(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with get_connection(database) as connection:
        source_id = connection.execute(
            "SELECT id FROM sources WHERE code='BEMOBI_IR'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO source_health(source_id, checked_at, status, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (source_id, "2026-08-20T18:00:00Z", "OK", json.dumps({"result": {}})),
        )
        connection.commit()

    result = bemobi_source_status(database)

    assert result["overall_status"] == "UNKNOWN"
    assert all(
        item["status"] == "UNKNOWN"
        for item in result["items"]
        if item["key"] in {"ir", "result_release", "consensus", "xp_preview"}
    )


def test_source_status_includes_health_for_operational_sources(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with get_connection(database) as connection:
        source_id = connection.execute(
            "SELECT id FROM sources WHERE code='NORGES_BANK'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO source_health(source_id, checked_at, status, metadata_json)
            VALUES (?, ?, ?, '{}')
            """,
            (source_id, "2026-08-20T18:00:00Z", "OK"),
        )
        connection.commit()

    result = bemobi_source_status(database)
    by_key = {item["key"]: item for item in result["items"]}

    assert by_key["norges_bank"]["source"] == "Norges Bank"
    assert by_key["norges_bank"]["status"] == "OK"
    assert by_key["norges_bank"]["checked_at"] == "2026-08-20T18:00:00Z"

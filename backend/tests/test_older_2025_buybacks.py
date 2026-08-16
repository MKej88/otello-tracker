import json
from decimal import Decimal

from app.buybacks.coverage import buyback_coverage_gaps
from app.buybacks.official_backfill import seed_known_official_buybacks
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def _program_rows(connection, external_program_id: str):
    return connection.execute(
        """
        SELECT b.*, sd.metadata_json, s.code AS source_code
        FROM buybacks b
        JOIN buyback_programs p ON p.id = b.program_id
        JOIN source_documents sd ON sd.id = b.source_document_id
        JOIN sources s ON s.id = sd.source_id
        WHERE p.external_program_id = ?
        ORDER BY b.trade_date, b.id
        """,
        (external_program_id,),
    ).fetchall()


def test_april_2025_program_reconciles_from_zero_to_final_cumulative(tmp_path) -> None:
    database = str(tmp_path / "april.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        rows = _program_rows(connection, "otec-buyback-2025-04-07")

    assert len(rows) == 7
    assert rows[0]["trade_date"] == "2025-04-11"
    assert rows[0]["shares"] == rows[0]["cumulative_program_shares"] == 709_400
    assert rows[0]["amount_nok"] == rows[0]["cumulative_program_amount_nok"] == "6001694"

    assert rows[-1]["trade_date"] == "2025-05-23"
    assert rows[-1]["cumulative_program_shares"] == 3_151_820
    assert rows[-1]["cumulative_program_amount_nok"] == "29956543"
    assert rows[-1]["treasury_shares_after"] == 3_151_820

    assert sum(row["shares"] for row in rows) == 3_151_820
    weekly_amount = sum(Decimal(row["amount_nok"]) for row in rows)
    assert weekly_amount == Decimal("29956542")
    assert Decimal(rows[-1]["cumulative_program_amount_nok"]) - weekly_amount == Decimal("1")
    assert {row["source_code"] for row in rows} == {"EURONEXT"}

    may23 = rows[-1]
    metadata = json.loads(may23["metadata_json"])
    assert metadata["issuer_text_discrepancy"] is True
    assert "4,410,701" in metadata["discrepancy_note"]
    assert may23["amount_nok"] == "4407461"

    gaps = [
        gap for gap in buyback_coverage_gaps(database)
        if gap["program"] == "otec-buyback-2025-04-07"
    ]
    assert gaps == []


def test_june_2025_program_reconciles_exactly_to_completion(tmp_path) -> None:
    database = str(tmp_path / "june.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        rows = _program_rows(connection, "otec-buyback-2025-06-16")

    assert len(rows) == 10
    assert rows[0]["trade_date"] == "2025-06-20"
    assert rows[0]["shares"] == rows[0]["cumulative_program_shares"] == 500_600
    assert rows[0]["amount_nok"] == rows[0]["cumulative_program_amount_nok"] == "5968177"

    assert rows[-1]["trade_date"] == "2025-08-19"
    assert rows[-1]["cumulative_program_shares"] == 5_047_130
    assert rows[-1]["cumulative_program_amount_nok"] == "65114879"
    assert rows[-1]["treasury_shares_after"] == 8_198_950

    assert sum(row["shares"] for row in rows) == 5_047_130
    assert sum(Decimal(row["amount_nok"]) for row in rows) == Decimal("65114879")
    assert {row["source_code"] for row in rows} == {"EURONEXT"}

    gaps = [
        gap for gap in buyback_coverage_gaps(database)
        if gap["program"] == "otec-buyback-2025-06-16"
    ]
    assert gaps == []


def test_august_2025_treasury_chain_increases_from_prior_program(tmp_path) -> None:
    database = str(tmp_path / "treasury.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        april_last = connection.execute(
            """
            SELECT treasury_shares_after FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2025-04-07'
            ORDER BY b.trade_date DESC LIMIT 1
            """
        ).fetchone()
        june_last = connection.execute(
            """
            SELECT treasury_shares_after FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2025-06-16'
            ORDER BY b.trade_date DESC LIMIT 1
            """
        ).fetchone()

    assert april_last["treasury_shares_after"] == 3_151_820
    assert june_last["treasury_shares_after"] == 8_198_950
    assert june_last["treasury_shares_after"] - april_last["treasury_shares_after"] == 5_047_130

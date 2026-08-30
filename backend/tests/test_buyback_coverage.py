from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator

from app.buybacks import coverage
from app.buybacks.coverage import buyback_coverage_gaps
from app.db.connection import get_connection
from app.buybacks.euronext import BuybackStatus, ingest_buyback_status
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def _status(
    *,
    end: str,
    shares: int,
    amount: str,
    cumulative_shares: int,
    cumulative_amount: str,
    treasury: int,
) -> BuybackStatus:
    return BuybackStatus(
        program_reference_date="2026-02-09",
        period_start=end,
        period_end=end,
        period_shares=shares,
        period_avg_price_nok=Decimal(amount) / Decimal(shares),
        period_amount_nok=Decimal(amount),
        cumulative_program_shares=cumulative_shares,
        cumulative_program_avg_price_nok=Decimal(cumulative_amount)
        / Decimal(cumulative_shares),
        cumulative_program_amount_nok=Decimal(cumulative_amount),
        max_program_shares=3_689_541,
        treasury_shares_after=treasury,
    )


def test_cumulative_values_expose_missing_week(tmp_path) -> None:
    database = str(tmp_path / "coverage.db")
    init_database(database)
    seed_curated_history(database)

    ingest_buyback_status(
        parsed=_status(
            end="2026-04-17",
            shares=100,
            amount="1000",
            cumulative_shares=100,
            cumulative_amount="1000",
            treasury=100,
        ),
        url="https://example.invalid/week-1",
        published_at="2026-04-17T20:00:00Z",
        database_path=database,
        source_code="EURONEXT",
    )
    ingest_buyback_status(
        parsed=_status(
            end="2026-04-30",
            shares=50,
            amount="500",
            cumulative_shares=175,
            cumulative_amount="1750",
            treasury=175,
        ),
        url="https://example.invalid/week-3",
        published_at="2026-04-30T20:00:00Z",
        database_path=database,
        source_code="EURONEXT",
    )

    gaps = buyback_coverage_gaps(database)
    assert len(gaps) == 1
    assert gaps[0]["missing_shares"] == 25
    assert gaps[0]["missing_amount_nok"] == "250"
    assert gaps[0]["after_date"] == "2026-04-17"
    assert gaps[0]["before_date"] == "2026-04-30"


def test_coverage_reads_all_programs_with_one_query(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "coverage-query-count.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        source_id = connection.execute(
            "SELECT id FROM source_documents ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        connection.executemany(
            """
            INSERT INTO buyback_programs (
                external_program_id, announced_at, start_date, source_document_id
            ) VALUES (?, ?, ?, ?)
            """,
            (
                ("program-1", "2026-01-01", "2026-01-02", source_id),
                ("program-2", "2026-02-01", "2026-02-02", source_id),
            ),
        )
        program_ids = {
            row["external_program_id"]: row["id"]
            for row in connection.execute(
                "SELECT id, external_program_id FROM buyback_programs"
            ).fetchall()
        }
        connection.executemany(
            """
            INSERT INTO buybacks (
                program_id, trade_date, shares, avg_price_nok, amount_nok,
                cumulative_program_shares, cumulative_program_amount_nok,
                source_document_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    program_ids["program-1"],
                    "2026-01-09",
                    10,
                    "10",
                    "100",
                    10,
                    "100",
                    source_id,
                ),
                (
                    program_ids["program-2"],
                    "2026-02-09",
                    10,
                    "10",
                    "100",
                    15,
                    "150",
                    source_id,
                ),
            ),
        )
        connection.commit()

    statements: list[str] = []
    real_get_connection = get_connection

    @contextmanager
    def traced_connection(database_path: str | None = None) -> Iterator:
        with real_get_connection(database_path) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(coverage, "get_connection", traced_connection)

    gaps = buyback_coverage_gaps(database)

    selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 1
    assert len(gaps) == 1
    assert gaps[0]["program"] == "program-2"
    assert gaps[0]["missing_shares"] == 5

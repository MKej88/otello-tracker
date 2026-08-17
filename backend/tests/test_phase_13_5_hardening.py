from __future__ import annotations

from datetime import date

from app.buybacks.activity import seed_otec_activity_history
from app.buybacks.forecast import buyback_forecast
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document
from app.marketdata.backfill import import_euronext_otec_csv, market_data_status
from app.marketdata.oslo_calendar import is_oslo_bors_trading_day, oslo_bors_trading_days


def _seed_program(database: str, *, status: str = "ACTIVE", end_date: str | None = None) -> None:
    with get_connection(database) as connection:
        document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id=f"phase-13-5-program-{status}-{end_date}",
            document_type="REGULATORY_NEWS",
            title="Phase 13.5 program test",
            url="https://newsweb.oslobors.no/message/test-phase-13-5",
        )
        cursor = connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, end_date, max_shares,
                max_price_nok, status, source_document_id, notes
            ) VALUES ('otec-buyback-phase-13-5', '2026-06-08T00:00:00Z',
                      '2026-06-08', ?, 2192046, '20', ?, ?, 'test')
            """,
            (end_date, status, document_id),
        )
        program_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO buybacks(
                program_id, period_start, trade_date, shares, avg_price_nok, amount_nok,
                cumulative_program_shares, treasury_shares_after, source_document_id
            ) VALUES (?, '2026-08-10', '2026-08-14', 59512, '17', '1011704',
                      600393, 5600393, ?)
            """,
            (program_id, document_id),
        )
        connection.commit()


def test_market_data_status_is_empty_on_clean_database(tmp_path) -> None:
    database = str(tmp_path / "empty-market.db")
    init_database(database)
    result = market_data_status(database)
    assert result["status"] == "empty"
    assert set(result["missing_components"]) == {"BMOB3", "OTEC", "BRL_NOK", "USD_NOK"}


def test_market_data_status_is_partial_when_only_one_component_exists(tmp_path) -> None:
    database = str(tmp_path / "partial-market.db")
    init_database(database)
    import_euronext_otec_csv(
        "Date,Closing Price\n14/08/2026,17.20\n",
        database_path=database,
    )
    result = market_data_status(database)
    assert result["status"] == "partial"
    assert result["OTEC"]["count"] == 1
    assert set(result["missing_components"]) == {"BMOB3", "BRL_NOK", "USD_NOK"}


def test_oslo_calendar_matches_euronext_2026_full_day_closures() -> None:
    assert not is_oslo_bors_trading_day(date(2026, 4, 2))  # Maundy Thursday
    assert not is_oslo_bors_trading_day(date(2026, 4, 3))  # Good Friday
    assert not is_oslo_bors_trading_day(date(2026, 4, 6))  # Easter Monday
    assert is_oslo_bors_trading_day(date(2026, 4, 1))  # half trading day, still open
    assert not is_oslo_bors_trading_day(date(2026, 12, 24))
    assert not is_oslo_bors_trading_day(date(2026, 12, 31))
    assert [item.isoformat() for item in oslo_bors_trading_days(date(2026, 3, 30), date(2026, 4, 3))] == [
        "2026-03-30",
        "2026-03-31",
        "2026-04-01",
    ]


def test_buyback_forecast_ignores_completed_program(tmp_path) -> None:
    database = str(tmp_path / "completed-program.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_program(database, status="COMPLETED")
    result = buyback_forecast(database, as_of_date="2026-08-17")
    assert result["ready"] is False
    assert result["status"] == "NO_ACTIVE_PROGRAM"


def test_buyback_forecast_ignores_expired_active_program(tmp_path) -> None:
    database = str(tmp_path / "expired-program.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_program(database, status="ACTIVE", end_date="2026-08-15")
    result = buyback_forecast(database, as_of_date="2026-08-17")
    assert result["ready"] is False
    assert result["status"] == "NO_ACTIVE_PROGRAM"

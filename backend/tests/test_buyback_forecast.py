from __future__ import annotations

from app.buybacks.activity import market_activity_status, seed_otec_activity_history
from app.buybacks.forecast import buyback_forecast
from app.buybacks.program_terms import parse_program_terms
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document


def test_parse_program_terms_from_weekly_status() -> None:
    text = """
    Reference is made to the stock exchange notice from 8 June 2026 announcing the
    initiation of the share buyback program. The maximum consideration to be paid for
    shares acquired under this buyback program is NOK 20 per share and the maximum
    number of shares that can be purchased under this buyback program is 2,192,046.
    """
    result = parse_program_terms(text)
    assert result["program_reference_date"] == "2026-06-08"
    assert str(result["max_price_nok"]) == "20"
    assert result["max_shares"] == 2_192_046


def test_euronext_activity_seed_has_current_20_day_history(tmp_path) -> None:
    database = str(tmp_path / "activity.db")
    init_database(database)
    result = seed_otec_activity_history(database)
    status = market_activity_status(database)
    assert result["rows"] > 500
    assert status["status"] == "ok"
    assert status["from"] == "2024-08-19"
    assert status["to"] == "2026-08-14"
    assert status["positive_days"] >= 490


def _seed_current_program(database: str) -> None:
    weeks = [
        ("2026-06-08", "2026-06-12", 79_600, 79_600),
        ("2026-06-15", "2026-06-19", 72_009, 151_609),
        ("2026-06-22", "2026-06-26", 52_419, 204_028),
        ("2026-06-29", "2026-07-03", 63_554, 267_582),
        ("2026-07-06", "2026-07-10", 65_300, 332_882),
        ("2026-07-13", "2026-07-17", 52_599, 385_481),
        ("2026-07-20", "2026-07-24", 50_500, 435_981),
        ("2026-07-27", "2026-07-31", 46_400, 482_381),
        ("2026-08-03", "2026-08-07", 58_500, 540_881),
        ("2026-08-10", "2026-08-14", 59_512, 600_393),
    ]
    with get_connection(database) as connection:
        document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="forecast-test-current-program",
            document_type="REGULATORY_NEWS",
            title="Forecast test current program",
            url="https://newsweb.oslobors.no/message/test",
        )
        cursor = connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, max_shares,
                max_price_nok, status, source_document_id, notes
            ) VALUES ('otec-buyback-2026-06-08', '2026-06-08T00:00:00Z',
                      '2026-06-08', 2192046, '20', 'ACTIVE', ?, 'test')
            """,
            (document_id,),
        )
        program_id = int(cursor.lastrowid)
        for start, end, shares, cumulative in weeks:
            connection.execute(
                """
                INSERT INTO buybacks(
                    program_id, period_start, trade_date, shares, avg_price_nok, amount_nok,
                    cumulative_program_shares, treasury_shares_after, source_document_id
                ) VALUES (?, ?, ?, ?, '17', ?, ?, ?, ?)
                """,
                (
                    program_id,
                    start,
                    end,
                    shares,
                    str(shares * 17),
                    cumulative,
                    5_000_000 + cumulative,
                    document_id,
                ),
            )
        connection.commit()


def test_current_program_forecast_matches_walk_forward_backtest_without_weekly_cash(tmp_path) -> None:
    database = str(tmp_path / "forecast.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_current_program(database)

    result = buyback_forecast(database, as_of_date="2026-08-17")
    assert result["ready"] is True
    assert result["forecast_week"] == {
        "from": "2026-08-17",
        "to": "2026-08-21",
        "expected_trading_days": 5,
        "trading_dates": [
            "2026-08-17",
            "2026-08-18",
            "2026-08-19",
            "2026-08-20",
            "2026-08-21",
        ],
    }
    assert result["volume_model"]["adv20_shares"] == 52789.4
    assert result["volume_model"]["week_start_capacity_estimate_shares"] == 65987
    assert result["program"]["remaining_shares"] == 1_591_653
    assert result["price_model"]["state"] == "OPEN"
    assert 61_000 <= result["estimate"]["base_case_shares"] <= 63_000
    assert result["estimate"]["low_shares"] < result["estimate"]["base_case_shares"]
    assert result["estimate"]["high_shares"] > result["estimate"]["base_case_shares"]
    assert result["estimate"]["confidence"] == "HIGH"
    assert result["active_program_backtest"]["median_ape_pct"] < 10


def test_price_cap_blocks_point_estimate_but_keeps_scenario_range(tmp_path) -> None:
    database = str(tmp_path / "forecast-cap.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_current_program(database)
    with get_connection(database) as connection:
        connection.execute(
            "UPDATE buyback_programs SET max_price_nok='16' WHERE external_program_id='otec-buyback-2026-06-08'"
        )
        connection.commit()

    result = buyback_forecast(database, as_of_date="2026-08-17")
    assert result["status"] == "PRICE_CAP_BLOCKED"
    assert result["estimate"]["base_case_shares"] == 0
    assert result["estimate"]["low_shares"] == 0
    assert result["estimate"]["high_shares"] > 0
    assert result["estimate"]["confidence"] == "LOW"

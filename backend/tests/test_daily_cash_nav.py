import json
from decimal import Decimal

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.nav.cash_curve import rebuild_daily_cash
from app.nav.daily_nav import rebuild_daily_core_nav


def _source_id(connection, code: str) -> int:
    return int(connection.execute("SELECT id FROM sources WHERE code = ?", (code,)).fetchone()["id"])


def _instrument_id(connection, symbol: str) -> int:
    return int(connection.execute("SELECT id FROM instruments WHERE symbol = ?", (symbol,)).fetchone()["id"])


def _insert_fx(connection, day: str, base: str, rate: str) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
        VALUES (?, 'NOK', ?, ?, ?)
        """,
        (base, f"{day}T16:00:00Z", rate, _source_id(connection, "ECB")),
    )


def _insert_price(connection, day: str, symbol: str, price: str, source: str) -> None:
    connection.execute(
        """
        INSERT INTO market_prices(
            instrument_id, observed_at, trading_date, price_type, price, currency,
            source_id, quality, metadata_json
        ) VALUES (?, ?, ?, 'CLOSE', ?, ?, ?, 'DIRECT', '{}')
        """,
        (
            _instrument_id(connection, symbol),
            f"{day}T16:30:00Z",
            day,
            price,
            "NOK" if symbol == "OTEC" else "BRL",
            _source_id(connection, source),
        ),
    )


def test_daily_cash_reconciles_reported_anchors_and_derives_distributions(tmp_path) -> None:
    database = str(tmp_path / "daily.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        anchor_dates = [
            row["as_of_date"]
            for row in connection.execute(
                "SELECT as_of_date FROM cash_anchors WHERE anchor_type = 'REPORTED'"
            )
        ]
        for day in anchor_dates:
            _insert_fx(connection, day, "USD", "10")
        for day in (
            "2022-04-12", "2023-04-12", "2024-05-02", "2025-01-07",
            "2025-05-09", "2025-12-01", "2025-12-22", "2026-05-27",
        ):
            _insert_fx(connection, day, "BRL", "2")
        connection.commit()

    result = rebuild_daily_cash(database, end_date="2026-06-30")
    assert result["periods"] == 9
    assert result["last_reported_anchor"] == "2025-12-31"

    with get_connection(database) as connection:
        year_end_2022 = connection.execute(
            "SELECT cash_nok, quality FROM cash_daily_estimates WHERE estimate_date = '2022-12-31'"
        ).fetchone()
        assert Decimal(year_end_2022["cash_nok"]) == Decimal("183730000")
        assert year_end_2022["quality"] == "REPORTED"

        distribution = connection.execute(
            """
            SELECT amount_nok, confidence FROM cash_movements
            WHERE movement_type = 'OTELLO_DISTRIBUTION'
            """
        ).fetchone()
        assert Decimal(distribution["amount_nok"]) == Decimal("-1913094309")
        assert distribution["confidence"] == "CONFIRMED"

        bemobi = connection.execute(
            """
            SELECT COUNT(*) AS n, MIN(confidence) AS confidence
            FROM cash_movements
            WHERE movement_type IN ('BEMOBI_DIVIDEND', 'BEMOBI_JCP')
            """
        ).fetchone()
        assert bemobi["n"] == 8
        assert bemobi["confidence"] == "ESTIMATED"

        calibration = connection.execute(
            """
            SELECT known_movements_nok, residual_nok, calendar_days
            FROM cash_period_calibrations
            WHERE start_anchor_date = '2022-06-30' AND end_anchor_date = '2022-12-31'
            """
        ).fetchone()
        assert Decimal(calibration["known_movements_nok"]) == Decimal("-1913094309")
        assert calibration["calendar_days"] == 184

        forecast = connection.execute(
            "SELECT quality FROM cash_daily_estimates WHERE estimate_date = '2026-06-30'"
        ).fetchone()
        assert forecast["quality"] == "FORECAST_PARTIAL"


def test_daily_nav_prefers_euronext_otec_over_investing_duplicate(tmp_path) -> None:
    database = str(tmp_path / "nav.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        anchor_dates = [
            row["as_of_date"]
            for row in connection.execute(
                "SELECT as_of_date FROM cash_anchors WHERE anchor_type = 'REPORTED'"
            )
        ]
        for day in anchor_dates:
            _insert_fx(connection, day, "USD", "10")
        for day in (
            "2022-04-12", "2023-04-12", "2024-05-02", "2025-01-07",
            "2025-05-09", "2025-12-01", "2025-12-22", "2026-05-27",
        ):
            _insert_fx(connection, day, "BRL", "2")
        _insert_fx(connection, "2024-06-28", "BRL", "2")
        _insert_price(connection, "2024-06-28", "BMOB3", "20", "B3")
        _insert_price(connection, "2024-06-28", "OTEC", "8", "EURONEXT")
        _insert_price(connection, "2024-06-28", "OTEC", "99", "INVESTING")
        connection.commit()

    rebuild_daily_cash(database, end_date="2025-12-31")
    result = rebuild_daily_core_nav(
        database, start_date="2024-06-28", end_date="2024-06-28"
    )
    assert result["written"] == 1

    with get_connection(database) as connection:
        row = connection.execute(
            """
            SELECT otec_price_nok, nav_per_share_nok, components_json, status
            FROM nav_snapshots
            WHERE calculation_version = 'core-market-nav-daily-v1'
            """
        ).fetchone()
        assert Decimal(row["otec_price_nok"]) == Decimal("8")
        assert Decimal(row["nav_per_share_nok"]) > 0
        assert row["status"] in {"ESTIMATED", "DEGRADED"}
        components = json.loads(row["components_json"])
        assert components["otec"]["price_source"] == "EURONEXT"

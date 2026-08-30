import sqlite3
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db.migration_runner import init_database
from app.db.repository import upsert_fx_rate
from app.fx_backtest import _load_rate_lookup, fx_backtest_summary
from app.history.economic_nav_inputs import seed_economic_nav_inputs
from app.main import app
from app.settings import settings


def _seed_rate(database_path: str, *, currency: str, day: str, rate: str) -> None:
    from app.db.connection import get_connection

    with get_connection(database_path) as connection:
        upsert_fx_rate(
            connection,
            base_currency=currency,
            quote_currency="NOK",
            observed_at=f"{day}T00:00:00Z",
            rate=Decimal(rate),
            source_code="MANUAL",
        )
        connection.commit()


def test_fx_rate_lookup_batches_many_dates_into_one_query() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE sources (id INTEGER PRIMARY KEY, code TEXT);
        CREATE TABLE fx_rates (
            id INTEGER PRIMARY KEY,
            base_currency TEXT,
            quote_currency TEXT,
            observed_at TEXT,
            rate TEXT,
            source_id INTEGER
        );
        INSERT INTO sources VALUES (1, 'NORGES_BANK');
        """)
    first_day = date(2025, 1, 1)
    for offset in range(100):
        day = (first_day + timedelta(days=offset)).isoformat()
        connection.execute(
            "INSERT INTO fx_rates VALUES (NULL, 'USD', 'NOK', ?, '10', 1)",
            (f"{day}T00:00:00Z",),
        )
        connection.execute(
            "INSERT INTO fx_rates VALUES (NULL, 'BRL', 'NOK', ?, '2', 1)",
            (f"{day}T00:00:00Z",),
        )

    queries: list[str] = []
    connection.set_trace_callback(queries.append)
    last_day = (first_day + timedelta(days=99)).isoformat()
    lookup = _load_rate_lookup(connection, first_day.isoformat(), last_day)
    for offset in range(100):
        assert lookup((first_day + timedelta(days=offset)).isoformat()) is not None

    selects = [
        query for query in queries if query.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 1


def test_fx_backtest_uses_start_anchor_without_lookahead(tmp_path) -> None:
    database_path = str(tmp_path / "fx.db")
    init_database(database_path)
    seed_economic_nav_inputs(database_path)

    _seed_rate(database_path, currency="USD", day="2023-12-31", rate="10.00")
    _seed_rate(database_path, currency="BRL", day="2023-12-31", rate="2.00")
    _seed_rate(database_path, currency="USD", day="2024-12-31", rate="12.00")
    _seed_rate(database_path, currency="BRL", day="2024-12-31", rate="1.80")

    result = fx_backtest_summary(database_path)
    period = next(
        item for item in result["periods"] if item.get("period_end") == "2024-12-31"
    )

    # Start anchor 31.12.2023: USD 4.919m, BRL eq USD 2.266m and
    # USD 7.391m residual treated as NOK hypothesis. No 2024 flows are seeded in this test.
    start_usd = Decimal("4919000")
    start_brl = Decimal("2266000") * Decimal("10.00") / Decimal("2.00")
    start_nok = Decimal("7391000") * Decimal("10.00")
    start_value = Decimal("14576000")
    end_value = (
        start_usd
        + start_nok / Decimal("12.00")
        + start_brl * Decimal("1.80") / Decimal("12.00")
    )
    expected_fx_m = (end_value - start_value) / Decimal("1000000")

    assert period["ready"] is True
    assert period["applied_known_movements"] == 0
    assert abs(Decimal(str(period["model_cash_fx_usd_m"])) - expected_fx_m) < Decimal(
        "0.0000001"
    )
    assert period["actual_cash_fx_usd_m"] == -1.51
    assert period["reported_pnl_fx_usd_m"] == -0.178
    assert period["method"] == "start-anchor-known-flows-daily-fx-v1"


def test_fx_backtest_returns_not_ready_without_historical_rates(tmp_path) -> None:
    database_path = str(tmp_path / "missing-fx.db")
    init_database(database_path)
    seed_economic_nav_inputs(database_path)

    payload = fx_backtest_summary(database_path)
    assert payload["ready"] is False
    assert payload["reason"] == "no_backtest_period_ready"
    assert all(
        period["reason"] == "missing_historical_fx_rates"
        for period in payload["periods"]
    )


def test_fx_backtest_endpoint_returns_structured_payload(tmp_path) -> None:
    previous_path = settings.database_path
    settings.database_path = str(tmp_path / "api-fx.db")
    try:
        with TestClient(app) as client:
            response = client.get("/api/dashboard/fx-backtest")
            assert response.status_code == 200
            payload = response.json()
            assert isinstance(payload["ready"], bool)
            if not payload["ready"]:
                assert "reason" in payload
    finally:
        settings.database_path = previous_path

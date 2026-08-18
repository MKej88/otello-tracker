from decimal import Decimal

from fastapi.testclient import TestClient

from app.db.migration_runner import init_database
from app.db.repository import upsert_fx_rate
from app.fx_backtest import fx_backtest_summary
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


def test_fx_backtest_uses_start_anchor_without_lookahead(tmp_path) -> None:
    database_path = str(tmp_path / "fx.db")
    init_database(database_path)
    seed_economic_nav_inputs(database_path)

    _seed_rate(database_path, currency="USD", day="2023-12-31", rate="10.00")
    _seed_rate(database_path, currency="BRL", day="2023-12-31", rate="2.00")
    _seed_rate(database_path, currency="USD", day="2024-12-31", rate="12.00")
    _seed_rate(database_path, currency="BRL", day="2024-12-31", rate="1.80")

    result = fx_backtest_summary(database_path)
    period = next(item for item in result["periods"] if item.get("period_end") == "2024-12-31")

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
    assert abs(Decimal(str(period["model_cash_fx_usd_m"])) - expected_fx_m) < Decimal("0.0000001")
    assert period["actual_cash_fx_usd_m"] == -1.51
    assert period["reported_pnl_fx_usd_m"] == -0.178
    assert period["method"] == "start-anchor-known-flows-daily-fx-v1"


def test_fx_backtest_endpoint_fails_softly_when_historical_rates_are_missing(tmp_path) -> None:
    previous_path = settings.database_path
    settings.database_path = str(tmp_path / "api-fx.db")
    try:
        with TestClient(app) as client:
            response = client.get("/api/dashboard/fx-backtest")
            assert response.status_code == 200
            payload = response.json()
            assert payload["ready"] is False
            assert payload["reason"] in {"no_backtest_period_ready", "missing_reported_fx_outcomes"}
    finally:
        settings.database_path = previous_path

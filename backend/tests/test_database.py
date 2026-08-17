from decimal import Decimal

from fastapi.testclient import TestClient

from app.db.connection import get_connection
from app.db.migration_runner import database_status, init_database
from app.db.repository import (
    create_source_document,
    decimal_text,
    record_provenance,
    upsert_fx_rate,
    upsert_market_price,
)
from app.main import app
from app.settings import settings


def test_migrations_are_idempotent_and_seed_reference_data(tmp_path) -> None:
    database_path = str(tmp_path / "otello.db")

    assert init_database(database_path) == ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008", "0009", "0010", "0011", "0012"]
    assert init_database(database_path) == []

    status = database_status(database_path)
    assert status["latest_migration"] == "0012"
    assert status["table_counts"]["sources"] == 11
    assert status["table_counts"]["instruments"] == 2
    assert status["table_counts"]["company_news"] == 0
    assert status["table_counts"]["other_net_assets_reported_anchors"] == 0
    assert status["table_counts"]["other_net_assets_daily_estimates"] == 0

    with get_connection(database_path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        symbols = {row["symbol"] for row in connection.execute("SELECT symbol FROM instruments")}
        assert symbols == {"OTEC", "BMOB3"}

        cash_columns = {row["name"] for row in connection.execute("PRAGMA table_info(cash_anchors)")}
        assert {"reported_amount", "reported_currency", "fx_rate_to_nok"} <= cash_columns

        movement_columns = {row["name"] for row in connection.execute("PRAGMA table_info(cash_movements)")}
        assert "corporate_action_id" in movement_columns

        action_columns = {row["name"] for row in connection.execute("PRAGMA table_info(corporate_actions)")}
        assert "quantity" in action_columns

        buyback_columns = {row["name"] for row in connection.execute("PRAGMA table_info(buybacks)")}
        assert {"cumulative_program_avg_price_nok", "cumulative_program_amount_nok"} <= buyback_columns

        nav_columns = {row["name"] for row in connection.execute("PRAGMA table_info(nav_snapshots)")}
        assert {"nav_scope", "components_json", "quality_notes"} <= nav_columns

        ona_columns = {row["name"] for row in connection.execute("PRAGMA table_info(other_net_assets_anchors)")}
        assert {"reported_anchor_id", "amount_usd", "fx_rate_to_nok", "quality", "inputs_hash"} <= ona_columns

        reported_ona_columns = {row["name"] for row in connection.execute("PRAGMA table_info(other_net_assets_reported_anchors)")}
        assert {"associated_receivable_reported", "base_other_net_assets_reported"} <= reported_ona_columns

        daily_ona_columns = {row["name"] for row in connection.execute("PRAGMA table_info(other_net_assets_daily_estimates)")}
        assert {
            "base_amount_usd", "base_amount_nok", "associated_receivable_nok",
            "receivable_quality", "receivable_components_json",
        } <= daily_ona_columns

        market_columns = {row["name"] for row in connection.execute("PRAGMA table_info(market_prices)")}
        assert {"quality", "metadata_json"} <= market_columns
        assert connection.execute("SELECT COUNT(*) FROM sources WHERE code = 'INVESTING'").fetchone()[0] == 1
        mfn = connection.execute("SELECT is_official, source_type FROM sources WHERE code = 'MFN'").fetchone()
        assert mfn["is_official"] == 0
        assert mfn["source_type"] == "OTHER"
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='cash_daily_estimates'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='cash_period_calibrations'").fetchone()[0] == 1


def test_financial_values_are_stored_as_exact_decimal_text(tmp_path) -> None:
    database_path = str(tmp_path / "otello.db")
    init_database(database_path)

    assert decimal_text(Decimal("17.20")) == "17.20"
    assert decimal_text("1.720000") == "1.720000"

    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="MANUAL",
            external_id="test-price-1",
            document_type="TEST",
            title="Test source document",
            url="manual://test-price-1",
        )

        price_id = upsert_market_price(
            connection,
            symbol="OTEC",
            observed_at="2026-08-16T14:25:00Z",
            trading_date="2026-08-16",
            price_type="LAST",
            price=Decimal("17.20"),
            currency="NOK",
            source_code="MANUAL",
            source_document_id=document_id,
            quality="RECONSTRUCTED",
            metadata={"reason": "test"},
        )
        upsert_market_price(
            connection,
            symbol="OTEC",
            observed_at="2026-08-16T14:25:00Z",
            trading_date="2026-08-16",
            price_type="LAST",
            price=Decimal("17.25"),
            currency="NOK",
            source_code="MANUAL",
            source_document_id=document_id,
            quality="DIRECT",
            metadata={"reason": "updated"},
        )

        fx_id = upsert_fx_rate(
            connection,
            base_currency="BRL",
            quote_currency="NOK",
            observed_at="2026-08-16T14:00:00Z",
            rate=Decimal("1.720000"),
            source_code="MANUAL",
            source_document_id=document_id,
        )

        provenance_id = record_provenance(
            connection,
            entity_table="market_prices",
            entity_id=price_id,
            field_name="price",
            source_document_id=document_id,
            source_locator="manual test",
            extraction_method="MANUAL",
            extracted_value="17.25",
        )
        connection.commit()

        price_row = connection.execute("SELECT price, quality, metadata_json FROM market_prices WHERE id = ?", (price_id,)).fetchone()
        fx_row = connection.execute("SELECT rate FROM fx_rates WHERE id = ?", (fx_id,)).fetchone()

        assert price_row["price"] == "17.25"
        assert price_row["quality"] == "DIRECT"
        assert '"updated"' in price_row["metadata_json"]
        assert fx_row["rate"] == "1.720000"
        assert connection.execute("SELECT COUNT(*) FROM market_prices").fetchone()[0] == 1
        assert provenance_id > 0


def test_database_status_api_initializes_schema(tmp_path) -> None:
    previous_path = settings.database_path
    settings.database_path = str(tmp_path / "api.db")
    try:
        with TestClient(app) as client:
            response = client.get("/api/system/database")
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "ok"
            assert payload["latest_migration"] == "0012"
            assert payload["table_counts"]["sources"] == 11
            assert payload["table_counts"]["company_news"] == 0
    finally:
        settings.database_path = previous_path

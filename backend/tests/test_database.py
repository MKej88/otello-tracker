from decimal import Decimal

from fastapi.testclient import TestClient

from app.db.connection import get_connection
from app.db.migrations import database_status, init_database
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

    assert init_database(database_path) == ["0001", "0002"]
    assert init_database(database_path) == []

    status = database_status(database_path)
    assert status["latest_migration"] == "0002"
    assert status["table_counts"]["sources"] == 9
    assert status["table_counts"]["instruments"] == 2

    with get_connection(database_path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        symbols = {
            row["symbol"]
            for row in connection.execute("SELECT symbol FROM instruments")
        }
        assert symbols == {"OTEC", "BMOB3"}


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

        price_row = connection.execute(
            "SELECT price FROM market_prices WHERE id = ?", (price_id,)
        ).fetchone()
        fx_row = connection.execute(
            "SELECT rate FROM fx_rates WHERE id = ?", (fx_id,)
        ).fetchone()

        assert price_row["price"] == "17.25"
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
            assert payload["latest_migration"] == "0002"
            assert payload["table_counts"]["sources"] == 9
    finally:
        settings.database_path = previous_path

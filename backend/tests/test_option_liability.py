from __future__ import annotations

from decimal import Decimal

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import (
    create_source_document,
    instrument_id,
    upsert_fx_rate,
    upsert_market_price,
)
from app.nav.option_liability import black_scholes_call, option_liability_for_day


def _seed_market_inputs(database_path: str) -> int:
    with get_connection(database_path) as connection:
        market_doc = create_source_document(
            connection,
            source_code="EURONEXT",
            external_id="option-test-otec",
            document_type="MARKET_DATA",
            title="OTEC option test",
            url="https://example.test/otec",
        )
        fx_doc = create_source_document(
            connection,
            source_code="ECB",
            external_id="option-test-fx",
            document_type="FX_DATA",
            title="USD/NOK option test",
            url="https://example.test/fx",
        )
        for day, price in (
            ("2025-12-31", "18.15"),
            ("2026-01-05", "25.00"),
            ("2026-01-06", "30.00"),
        ):
            upsert_market_price(
                connection,
                symbol="OTEC",
                observed_at=f"{day}T15:30:00Z",
                trading_date=day,
                price_type="CLOSE",
                price=price,
                currency="NOK",
                source_code="EURONEXT",
                source_document_id=market_doc,
            )
        for day in ("2025-12-31", "2026-01-05"):
            upsert_fx_rate(
                connection,
                base_currency="USD",
                quote_currency="NOK",
                observed_at=f"{day}T14:00:00Z",
                rate="10.00",
                source_code="ECB",
                source_document_id=fx_doc,
            )
        connection.commit()
        return market_doc


def test_black_scholes_value_increases_with_otec_spot() -> None:
    common = {
        "strike": Decimal("12.5637"),
        "years": Decimal("2.5"),
        "risk_free_rate": Decimal("0.039"),
        "volatility": Decimal("0.234"),
    }
    low = black_scholes_call(Decimal("15"), **common)
    high = black_scholes_call(Decimal("25"), **common)
    assert high > low > 0


def test_option_liability_is_zero_before_program_grant(tmp_path) -> None:
    database_path = str(tmp_path / "otello.db")
    init_database(database_path)
    with get_connection(database_path) as connection:
        result = option_liability_for_day(connection, "2025-09-14")
    assert result is not None
    assert result["liability_nok"] == 0
    assert result["quality"] == "NONE"


def test_year_end_option_liability_reconciles_exactly_to_reported_usd_314k(tmp_path) -> None:
    database_path = str(tmp_path / "otello.db")
    init_database(database_path)
    _seed_market_inputs(database_path)

    with get_connection(database_path) as connection:
        result = option_liability_for_day(connection, "2025-12-31")

    assert result is not None
    assert result["quality"] == "REPORTED_CALIBRATED"
    assert result["liability_usd"] == Decimal("314000")
    assert result["liability_nok"] == Decimal("3140000.00")
    assert Decimal("0") < result["recognition_fraction"] < Decimal("1")
    assert result["strike_nok"] == Decimal("12.5637")


def test_post_report_liability_marks_to_market_when_otec_rises(tmp_path) -> None:
    database_path = str(tmp_path / "otello.db")
    init_database(database_path)
    _seed_market_inputs(database_path)

    with get_connection(database_path) as connection:
        at_25 = option_liability_for_day(connection, "2026-01-05")
        at_30 = option_liability_for_day(connection, "2026-01-06")

    assert at_25 is not None and at_30 is not None
    assert at_25["quality"] == "FORECAST_MARK_TO_MARKET"
    assert at_30["quality"] == "FORECAST_MARK_TO_MARKET"
    assert at_25["recognition_fraction"] == at_30["recognition_fraction"]
    assert at_30["liability_nok"] > at_25["liability_nok"]


def test_paid_otello_distribution_reduces_option_strike(tmp_path) -> None:
    database_path = str(tmp_path / "otello.db")
    init_database(database_path)
    source_document_id = _seed_market_inputs(database_path)

    with get_connection(database_path) as connection:
        connection.execute(
            """
            INSERT INTO corporate_actions(
                issuer_instrument_id, action_type, announcement_date, ex_date,
                record_date, payment_date, amount_per_share, currency,
                source_document_id, notes
            ) VALUES (?, 'DISTRIBUTION', '2026-01-01', '2026-01-02',
                      '2026-01-02', '2026-01-05', '1.00', 'NOK', ?, 'test')
            """,
            (instrument_id(connection, "OTEC"), source_document_id),
        )
        connection.commit()
        result = option_liability_for_day(connection, "2026-01-05")

    assert result is not None
    assert result["strike_nok"] == Decimal("11.5637")
    assert result["inputs"]["strike_adjustments"][0]["amount_per_share_nok"] == "1.00"

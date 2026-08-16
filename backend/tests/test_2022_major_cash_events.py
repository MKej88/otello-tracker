from decimal import Decimal

from app.buybacks.official_backfill import seed_known_official_buybacks
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import upsert_fx_rate
from app.history import seed_curated_history
from app.history.cash_events_2022 import seed_2022_cash_events


def _seed_test_fx(database: str) -> None:
    with get_connection(database) as connection:
        upsert_fx_rate(
            connection,
            base_currency="USD",
            quote_currency="NOK",
            observed_at="2022-01-14T16:00:00Z",
            rate="9.0",
            source_code="ECB",
        )
        upsert_fx_rate(
            connection,
            base_currency="BRL",
            quote_currency="NOK",
            observed_at="2022-04-20T16:00:00Z",
            rate="1.8",
            source_code="ECB",
        )
        connection.commit()


def test_major_2022_cash_events_use_original_currency_and_are_idempotent(tmp_path) -> None:
    database = str(tmp_path / "cash-events.db")
    init_database(database)
    seed_curated_history(database)
    _seed_test_fx(database)

    first = seed_2022_cash_events(database)
    second = seed_2022_cash_events(database)

    assert first["written"] == 2
    assert first["updated"] == 0
    assert first["missing_fx"] == []
    assert second["written"] == 0
    assert second["updated"] == 2
    assert second["missing_fx"] == []

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT movement_date, movement_type, amount_nok, amount_original, currency,
                   fx_rate_to_nok, confidence, description
            FROM cash_movements
            WHERE movement_date IN ('2022-01-15', '2022-04-20')
            ORDER BY movement_date
            """
        ).fetchall()

    assert len(rows) == 2
    assert dict(rows[0]) == {
        "movement_date": "2022-01-15",
        "movement_type": "OTHER",
        "amount_nok": "1725300000.0",
        "amount_original": "191700000",
        "currency": "USD",
        "fx_rate_to_nok": "9.0",
        "confidence": "CONFIRMED",
        "description": rows[0]["description"],
    }
    assert "AdColony" in rows[0]["description"]

    assert rows[1]["movement_type"] == "TAX"
    assert Decimal(rows[1]["amount_nok"]) == Decimal("-121202672.4")
    assert rows[1]["amount_original"] == "-67334818"
    assert rows[1]["currency"] == "BRL"
    assert rows[1]["fx_rate_to_nok"] == "1.8"
    assert rows[1]["confidence"] == "CONFIRMED"
    assert "BRL 67,334,818" in rows[1]["description"]


def test_march_2022_buyback_uses_effective_registered_share_count(tmp_path) -> None:
    database = str(tmp_path / "buyback-2022.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        buyback = connection.execute(
            """
            SELECT b.shares, b.avg_price_nok, b.amount_nok, b.treasury_shares_after,
                   s.code AS source_code
            FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            JOIN source_documents sd ON sd.id = b.source_document_id
            JOIN sources s ON s.id = sd.source_id
            WHERE p.external_program_id = 'otec-buyback-2022-03-21'
              AND b.trade_date = '2022-03-28'
            """
        ).fetchone()
        cash = connection.execute(
            """
            SELECT amount_nok, amount_original, currency, confidence
            FROM cash_movements
            WHERE movement_date = '2022-03-28' AND movement_type = 'OTELLO_BUYBACK'
            """
        ).fetchone()
        march7 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts WHERE effective_from = '2022-03-07'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        march28 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts WHERE effective_from = '2022-03-28'
              AND notes LIKE 'Treasury shares from %'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        june14 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts WHERE effective_from = '2022-06-14'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()

    assert dict(buyback) == {
        "shares": 10_000_000,
        "avg_price_nok": "27.5",
        "amount_nok": "275000000",
        "treasury_shares_after": 10_000_000,
        "source_code": "OTELLO_IR",
    }
    assert dict(cash) == {
        "amount_nok": "-275000000",
        "amount_original": "-275000000",
        "currency": "NOK",
        "confidence": "CONFIRMED",
    }
    assert dict(march7) == {
        "total_shares": 101_099_727,
        "treasury_shares": 0,
        "outstanding_shares": 101_099_727,
    }
    assert dict(march28) == {
        "total_shares": 101_099_727,
        "treasury_shares": 10_000_000,
        "outstanding_shares": 91_099_727,
    }
    assert dict(june14) == {
        "total_shares": 91_099_729,
        "treasury_shares": 0,
        "outstanding_shares": 91_099_729,
    }

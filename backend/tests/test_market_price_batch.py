from decimal import Decimal

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import upsert_market_prices


def test_market_price_batch_keeps_upsert_semantics_and_avoids_lookup_n_plus_one(
    tmp_path,
) -> None:
    database_path = str(tmp_path / "batch.db")
    init_database(database_path)
    statements: list[str] = []

    with get_connection(database_path) as connection:
        connection.set_trace_callback(statements.append)
        upsert_market_prices(
            connection,
            symbol="BMOB3",
            source_code="B3",
            price_type="CLOSE",
            currency="BRL",
            prices=(
                ("2026-09-04T23:59:59Z", "2026-09-04", Decimal("22.81")),
                ("2026-09-05T23:59:59Z", "2026-09-05", Decimal("23.10")),
            ),
        )
        upsert_market_prices(
            connection,
            symbol="BMOB3",
            source_code="B3",
            price_type="CLOSE",
            currency="BRL",
            prices=(("2026-09-04T23:59:59Z", "2026-09-04", Decimal("22.90")),),
        )
        rows = connection.execute("""
            SELECT trading_date, price FROM market_prices
            WHERE trading_date >= '2026-09-04'
            ORDER BY trading_date
            """).fetchall()

    lookup_queries = [
        statement
        for statement in statements
        if statement.startswith("SELECT id FROM sources")
        or statement.startswith("SELECT id FROM instruments")
    ]
    assert len(lookup_queries) == 4
    assert [(row["trading_date"], row["price"]) for row in rows] == [
        ("2026-09-04", "22.90"),
        ("2026-09-05", "23.10"),
    ]

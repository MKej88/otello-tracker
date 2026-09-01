from pathlib import Path

import pytest

from app.dashboard import bemobi_insights
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history

ROOT = Path(__file__).resolve().parents[2]


def _source(connection, code: str) -> int:
    row = connection.execute("SELECT id FROM sources WHERE code=?", (code,)).fetchone()
    return int(row["id"])


def _price(connection, day: str, price: str) -> None:
    instrument = connection.execute(
        "SELECT id FROM instruments WHERE symbol='BMOB3'"
    ).fetchone()["id"]
    connection.execute(
        """INSERT INTO market_prices(
        instrument_id, observed_at, trading_date, price_type, price, currency,
        source_id, quality) VALUES (?, ?, ?, 'CLOSE', ?, 'BRL', ?, 'DIRECT')""",
        (instrument, f"{day}T16:00:00Z", day, price, _source(connection, "B3")),
    )


def _fx(connection, day: str, rate: str) -> None:
    connection.execute(
        """INSERT INTO fx_rates(
        base_currency, quote_currency, observed_at, rate, source_id)
        VALUES ('BRL', 'NOK', ?, ?, ?)""",
        (f"{day}T16:00:00Z", rate, _source(connection, "NORGES_BANK")),
    )


def test_bemobi_insights_uses_existing_history_and_holdings(tmp_path) -> None:
    database = str(tmp_path / "bemobi.db")
    init_database(database)
    seed_curated_history(database)
    with get_connection(database) as connection:
        for day, price in (
            ("2025-09-01", "18"),
            ("2026-06-29", "19"),
            ("2026-07-30", "20"),
            ("2026-08-28", "22"),
            ("2026-08-31", "24"),
        ):
            _price(connection, day, price)
        _fx(connection, "2026-07-30", "1.8")
        _fx(connection, "2026-08-31", "2.0")
        document = connection.execute(
            "SELECT id FROM source_documents ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        connection.execute(
            """INSERT INTO cash_anchors(
            as_of_date, amount_nok, anchor_type, source_document_id)
            VALUES ('2026-06-30', '1', 'REPORTED', ?)""",
            (document,),
        )
        result = bemobi_insights(
            connection,
            as_of_date="2026-08-31",
            bemobi_value_nok="1500000000",
            shares_outstanding=75_000_000,
        )

    assert result["daily_pct"] == pytest.approx((24 / 22 - 1) * 100)
    assert result["month_reference_date"] == "2026-07-30"
    assert result["month_pct"] == pytest.approx(20)
    assert result["quarter_label"] == "Q2 26"
    assert result["quarter_reference_date"] == "2026-06-29"
    assert result["nav_effect_1m_per_share_nok"] is not None
    assert result["value_per_otec_share_nok"] == 20
    assert result["holding_shares"] == 32_719_588
    assert result["ownership_pct"] is not None
    assert result["range_1y"] == {"low": 18.0, "high": 24.0, "position_pct": 100.0}


def test_bemobi_insights_handles_missing_and_flat_history(tmp_path) -> None:
    database = str(tmp_path / "missing.db")
    init_database(database)
    with get_connection(database) as connection:
        missing = bemobi_insights(
            connection,
            as_of_date="2026-08-31",
            bemobi_value_nok=None,
            shares_outstanding=0,
        )
        _price(connection, "2026-08-31", "22")
        flat = bemobi_insights(
            connection,
            as_of_date="2026-08-31",
            bemobi_value_nok=None,
            shares_outstanding=0,
        )
    assert missing["range_1y"]["low"] is None
    assert flat["daily_pct"] is None and flat["month_pct"] is None
    assert flat["value_per_otec_share_nok"] is None
    assert flat["range_1y"] == {"low": 22.0, "high": 22.0, "position_pct": None}


def test_bemobi_card_has_labels_and_safe_fallbacks() -> None:
    page = (ROOT / "frontend/src/OverviewPage.tsx").read_text(encoding="utf-8")
    for text in (
        "Siste kurs",
        "NAV-effekt 1 mnd",
        "Verdi / OTEC-aksje",
        "Otello eier",
        "Sterkere BMOB3 = positivt for Otello NAV",
    ):
        assert text in page
    assert 'return "—"' in page and "Number.isFinite" in page
    assert "bemobi?.price_brl == null" in page
    assert "!Number.isFinite(bemobi.price_brl)" in page

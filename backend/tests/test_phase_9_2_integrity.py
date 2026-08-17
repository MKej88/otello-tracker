from dataclasses import replace
from decimal import Decimal

import pytest

from app.buybacks.collector import _publication_timestamp
from app.buybacks.euronext import BuybackStatus, ingest_buyback_status
from app.dashboard import dashboard_summary
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document
from app.history import seed_curated_history
from app.marketdata.investing_csv import parse_investing_historical_csv
from app.nav.cash_curve import _known_movements
from app.nav.daily_nav import CALCULATION_VERSION as CORE_VERSION
from app.nav.full_nav import FULL_CALCULATION_VERSION


def _insert_nav(connection, *, day: str, version: str, scope: str, nav: str) -> None:
    connection.execute(
        """
        INSERT INTO nav_snapshots(
            as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
            discount_pct, bemobi_value_nok, cash_estimate_nok,
            other_net_assets_nok, shares_outstanding, calculation_version,
            inputs_hash, status, nav_scope, components_json, quality_notes
        ) VALUES (?, '1000000000', ?, '10', '20', '900000000', '100000000',
                  '0', 100000000, ?, ?, 'BACKFILLED', ?, '{}', 'test')
        """,
        (f"{day}T23:59:59Z", nav, version, f"hash-{scope}-{day}", scope),
    )


def test_dashboard_falls_back_to_newer_core_when_full_is_stale(tmp_path) -> None:
    db = str(tmp_path / "dashboard-stale-full.db")
    init_database(db)
    with get_connection(db) as connection:
        _insert_nav(connection, day="2026-08-16", version=CORE_VERSION, scope="CORE", nav="20")
        _insert_nav(connection, day="2026-08-17", version=CORE_VERSION, scope="CORE", nav="21")
        _insert_nav(connection, day="2026-08-16", version=FULL_CALCULATION_VERSION, scope="FULL", nav="22")
        connection.commit()

    summary = dashboard_summary(db)
    assert summary["model_scope"] == "CORE"
    assert summary["as_of_date"] == "2026-08-17"
    assert summary["nav_per_share"] == 21.0

    with get_connection(db) as connection:
        _insert_nav(connection, day="2026-08-17", version=FULL_CALCULATION_VERSION, scope="FULL", nav="23")
        connection.commit()

    summary = dashboard_summary(db)
    assert summary["model_scope"] == "FULL"
    assert summary["as_of_date"] == "2026-08-17"
    assert summary["nav_per_share"] == 23.0


def test_investing_parser_accepts_decimal_comma_without_100x_scaling() -> None:
    rows = parse_investing_historical_csv(
        "Date;Price\n19/08/2024;17,20\n20/08/2024;17,35\n"
    )
    assert rows == [
        ("2024-08-19", Decimal("17.20")),
        ("2024-08-20", Decimal("17.35")),
    ]


def test_investing_parser_rejects_implausible_price() -> None:
    with pytest.raises(ValueError, match="Urealistisk OTEC-pris"):
        parse_investing_historical_csv("Date,Price\n08/19/2024,1720\n")


def test_mfn_timestamp_uses_oslo_dst_rules() -> None:
    assert _publication_timestamp("2026-01-15 12:34:56 Source Oslo Børs").endswith("+01:00")
    assert _publication_timestamp("2026-07-15 12:34:56 Source Oslo Børs").endswith("+02:00")


def test_cross_anchor_weekly_buyback_is_not_double_counted(tmp_path) -> None:
    db = str(tmp_path / "cross-anchor.db")
    init_database(db)
    with get_connection(db) as connection:
        connection.execute(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, amount_original,
                currency, description, confidence
            ) VALUES (
                '2025-07-04', 'OTELLO_BUYBACK', '-6250920', '-6250920', 'NOK',
                'Otello buyback: 513,000 shares during 2025-06-30–2025-07-04.',
                'CONFIRMED'
            )
            """
        )
        connection.commit()
        rows = _known_movements(connection, "2025-06-30", "2025-09-30")

    assert len(rows) == 1
    assert rows[0]["amount_nok"] == "-6250920"
    assert rows[0]["model_amount_nok"] == "0"
    assert rows[0]["timing_quality"] == "CROSS_ANCHOR_EXCLUDED"


def _sample_status(amount: str = "1117133") -> BuybackStatus:
    return BuybackStatus(
        program_reference_date="2026-06-08",
        period_start="2026-07-06",
        period_end="2026-07-10",
        period_shares=65_300,
        period_avg_price_nok=Decimal("17.11"),
        period_amount_nok=Decimal(amount),
        cumulative_program_shares=332_882,
        cumulative_program_avg_price_nok=Decimal("17.13"),
        cumulative_program_amount_nok=Decimal("5701775"),
        max_program_shares=2_192_046,
        treasury_shares_after=5_519_886,
    )


def test_weaker_buyback_source_cannot_rewrite_official_fact(tmp_path) -> None:
    db = str(tmp_path / "source-priority.db")
    init_database(db)
    seed_curated_history(db)

    official = ingest_buyback_status(
        parsed=_sample_status(),
        url="https://live.euronext.com/en/products/equities/company-news/2026-07-11-test",
        published_at="2026-07-11T21:49:00+02:00",
        database_path=db,
        source_code="EURONEXT",
    )
    assert official["source_applied"] is True

    with pytest.raises(ValueError, match="krever kontroll"):
        ingest_buyback_status(
            parsed=replace(_sample_status(), period_amount_nok=Decimal("999999")),
            url="https://mfn.se/a/test-mirror",
            published_at="2026-07-11T21:49:00+02:00",
            database_path=db,
            source_code="MFN",
        )

    with get_connection(db) as connection:
        row = connection.execute(
            """
            SELECT b.amount_nok, s.code AS source_code
            FROM buybacks b
            JOIN source_documents sd ON sd.id = b.source_document_id
            JOIN sources s ON s.id = sd.source_id
            WHERE b.trade_date = '2026-07-10'
            """
        ).fetchone()
    assert row["amount_nok"] == "1117133"
    assert row["source_code"] == "EURONEXT"


def test_source_document_refresh_merges_metadata_and_hash(tmp_path) -> None:
    db = str(tmp_path / "source-document.db")
    init_database(db)
    with get_connection(db) as connection:
        first = create_source_document(
            connection,
            source_code="MANUAL",
            external_id="doc-1",
            document_type="TEST",
            title="First",
            url="manual://first",
            metadata={"curated": True},
        )
        second = create_source_document(
            connection,
            source_code="MANUAL",
            external_id="doc-1",
            document_type="TEST",
            title="Updated",
            url="manual://updated",
            content_sha256="abc123",
            metadata={"refreshed": True},
        )
        connection.commit()
        row = connection.execute(
            "SELECT title, url, content_sha256, metadata_json FROM source_documents WHERE id = ?",
            (first,),
        ).fetchone()

    assert first == second
    assert row["title"] == "Updated"
    assert row["url"] == "manual://updated"
    assert row["content_sha256"] == "abc123"
    assert '"curated": true' in row["metadata_json"]
    assert '"refreshed": true' in row["metadata_json"]

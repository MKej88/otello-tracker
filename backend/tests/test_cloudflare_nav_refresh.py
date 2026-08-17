from __future__ import annotations

import asyncio
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
for path in (str(BACKEND), str(CLOUDFLARE_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.nav.cash_curve import rebuild_daily_cash as rebuild_reference_cash  # noqa: E402
from app.nav.intraday import rebuild_core_nav_for_date as rebuild_reference_core  # noqa: E402
from app.nav.option_liability import option_liability_for_day as reference_option  # noqa: E402
from cash_refresh import rebuild_daily_cash_if_changed  # noqa: E402
from nav_refresh import (  # noqa: E402
    CORE_VERSION,
    FULL_VERSION,
    rebuild_core_nav_for_date,
    rebuild_dirty_nav,
    resolve_nav_date,
)
from option_refresh import option_liability_for_day  # noqa: E402


class SqliteD1Repository:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        for migration in sorted((ROOT / "cloudflare" / "migrations").glob("*.sql")):
            self.connection.executescript(migration.read_text(encoding="utf-8"))
        self.connection.commit()

    async def run(self, sql: str, parameters=()):
        cursor = self.connection.execute(sql, parameters)
        self.connection.commit()
        return cursor

    async def all(self, sql: str, parameters=()):
        return [dict(row) for row in self.connection.execute(sql, parameters).fetchall()]

    async def first(self, sql: str, parameters=()):
        row = self.connection.execute(sql, parameters).fetchone()
        return dict(row) if row is not None else None


def _id(db: sqlite3.Connection, table: str, field: str, value: str) -> int:
    row = db.execute(f"SELECT id FROM {table} WHERE {field}=?", (value,)).fetchone()
    assert row is not None
    return int(row[0])


def _seed(repository: SqliteD1Repository) -> None:
    db = repository.connection
    newsweb = _id(db, "sources", "code", "NEWSWEB")
    euronext = _id(db, "sources", "code", "EURONEXT")
    b3 = _id(db, "sources", "code", "B3")
    ecb = _id(db, "sources", "code", "ECB")
    otec = _id(db, "instruments", "symbol", "OTEC")
    bmob3 = _id(db, "instruments", "symbol", "BMOB3")

    document_id = db.execute(
        """
        INSERT INTO source_documents(
            source_id,external_id,document_type,title,url,metadata_json
        ) VALUES (?, 'nav-worker-test', 'FINANCIAL_REPORT', 'NAV worker test',
                  'https://example.test/nav', '{}')
        """,
        (newsweb,),
    ).lastrowid

    for observed_at, rate in (
        ("2025-12-31T16:00:00Z", "10.0"),
        ("2026-06-30T16:00:00Z", "10.0"),
        ("2026-08-17T12:00:00Z", "10.0"),
    ):
        db.execute(
            """
            INSERT INTO fx_rates(
                base_currency,quote_currency,observed_at,rate,
                source_id,source_document_id,quality
            ) VALUES ('USD','NOK',?,?,?,?, 'DIRECT')
            """,
            (observed_at, rate, ecb, document_id),
        )
    for observed_at, rate in (
        ("2026-06-30T16:00:00Z", "1.90"),
        ("2026-08-17T12:00:00Z", "1.90"),
    ):
        db.execute(
            """
            INSERT INTO fx_rates(
                base_currency,quote_currency,observed_at,rate,
                source_id,source_document_id,quality
            ) VALUES ('BRL','NOK',?,?,?,?, 'DIRECT')
            """,
            (observed_at, rate, ecb, document_id),
        )

    db.execute(
        """
        INSERT INTO cash_anchors(
            as_of_date,reported_amount,reported_currency,
            anchor_type,source_document_id,notes
        ) VALUES ('2025-12-31','10000000','USD','REPORTED',?,'test')
        """,
        (document_id,),
    )
    db.execute(
        """
        INSERT INTO cash_anchors(
            as_of_date,reported_amount,reported_currency,
            anchor_type,source_document_id,notes
        ) VALUES ('2026-06-30','11000000','USD','REPORTED',?,'test')
        """,
        (document_id,),
    )
    db.execute(
        """
        INSERT INTO cash_movements(
            movement_date,movement_type,amount_nok,amount_original,currency,
            fx_rate_to_nok,description,source_document_id,confidence
        ) VALUES (
            '2026-08-17','OTELLO_BUYBACK','-1000000','-1000000','NOK','1',
            'Otello buyback: 100,000 shares during 2026-08-10–2026-08-17.',?,
            'CONFIRMED'
        )
        """,
        (document_id,),
    )

    db.execute(
        """
        INSERT INTO bemobi_holdings(
            effective_from,shares,ownership_pct,source_document_id,notes
        ) VALUES ('2025-01-01',60000000,'0.18',?,'test')
        """,
        (document_id,),
    )
    db.execute(
        """
        INSERT INTO otello_share_counts(
            effective_from,total_shares,treasury_shares,outstanding_shares,
            source_document_id,notes
        ) VALUES ('2025-01-01',100000000,10000000,90000000,?,'test')
        """,
        (document_id,),
    )

    db.execute(
        """
        INSERT INTO market_prices(
            instrument_id,observed_at,trading_date,price_type,price,currency,
            source_id,source_document_id,quality,metadata_json
        ) VALUES (?, '2025-12-31T15:00:00Z','2025-12-31','CLOSE','18.15','NOK',?,?,
                  'DIRECT','{}')
        """,
        (otec, euronext, document_id),
    )
    db.execute(
        """
        INSERT INTO market_prices(
            instrument_id,observed_at,trading_date,price_type,price,currency,
            source_id,source_document_id,quality,metadata_json
        ) VALUES (?, '2026-08-17T12:00:00Z','2026-08-17','LAST','20.00','NOK',?,?,
                  'DIRECT','{}')
        """,
        (otec, euronext, document_id),
    )
    db.execute(
        """
        INSERT INTO market_prices(
            instrument_id,observed_at,trading_date,price_type,price,currency,
            source_id,source_document_id,quality,metadata_json
        ) VALUES (?, '2026-08-17T15:00:00Z','2026-08-17','LAST','25.00','BRL',?,?,
                  'DIRECT','{}')
        """,
        (bmob3, b3, document_id),
    )

    reported_id = db.execute(
        """
        INSERT INTO other_net_assets_reported_anchors(
            as_of_date,other_net_assets_reported,associated_receivable_reported,
            base_other_net_assets_reported,source_document_id,notes,
            option_liability_reported,base_other_net_assets_ex_option_reported
        ) VALUES (
            '2025-12-31','-4750000','0','-4750000',?,'test','314000','-4436000'
        )
        """,
        (document_id,),
    ).lastrowid
    db.execute(
        """
        INSERT INTO other_net_assets_anchors(
            as_of_date,amount_usd,usd_nok_rate,amount_nok,source_document_id,
            reported_anchor_id,normalization_version,inputs_hash,notes
        ) VALUES (
            '2025-12-31','-4750000','10','-47500000',?,?,'v1','test','test'
        )
        """,
        (document_id, reported_id),
    )
    db.commit()


def _clone(source: SqliteD1Repository) -> SqliteD1Repository:
    clone = SqliteD1Repository()
    source.connection.backup(clone.connection)
    return clone


def _value(result, key: str):
    if isinstance(result, dict):
        return result[key]
    return getattr(result, key)


def test_worker_cash_matches_reference_and_dirty_state_skips_second_run() -> None:
    worker = SqliteD1Repository()
    _seed(worker)
    reference = _clone(worker)
    try:
        worker_result = asyncio.run(
            rebuild_daily_cash_if_changed(worker, end_date="2026-08-17", force=True)
        )
        reference_result = rebuild_reference_cash(reference.connection, end_date="2026-08-17")

        worker_cash = worker.connection.execute(
            "SELECT cash_nok,quality FROM cash_daily_estimates WHERE estimate_date='2026-08-17'"
        ).fetchone()
        reference_cash = reference.connection.execute(
            "SELECT cash_nok,quality FROM cash_daily_estimates WHERE estimate_date='2026-08-17'"
        ).fetchone()
        assert tuple(worker_cash) == tuple(reference_cash)
        assert worker_result["cross_anchor_exclusions"] == reference_result["cross_anchor_exclusions"]

        second = asyncio.run(
            rebuild_daily_cash_if_changed(worker, end_date="2026-08-17")
        )
        assert second["skipped"] is True
        assert second["reason"] == "cash_inputs_unchanged"
    finally:
        worker.connection.close()
        reference.connection.close()


def test_worker_option_liability_matches_reference() -> None:
    repository = SqliteD1Repository()
    _seed(repository)
    try:
        worker = asyncio.run(option_liability_for_day(repository, "2026-08-17"))
        reference = reference_option(repository.connection, "2026-08-17")
        assert worker is not None
        assert reference is not None
        assert Decimal(worker["liability_nok"]) == Decimal(_value(reference, "liability_nok"))
        assert Decimal(worker["liability_usd"]) == Decimal(_value(reference, "liability_usd"))
        assert Decimal(worker["strike_nok"]) == Decimal(_value(reference, "strike_nok"))
        assert worker["quality"] == _value(reference, "quality")
    finally:
        repository.connection.close()


def test_worker_core_nav_matches_reference() -> None:
    worker = SqliteD1Repository()
    _seed(worker)
    reference = _clone(worker)
    try:
        asyncio.run(rebuild_daily_cash_if_changed(worker, end_date="2026-08-17", force=True))
        rebuild_reference_cash(reference.connection, end_date="2026-08-17")

        worker_result = asyncio.run(
            rebuild_core_nav_for_date(worker, as_of_date="2026-08-17")
        )
        reference_result = rebuild_reference_core(reference.connection, as_of_date="2026-08-17")
        assert Decimal(worker_result["nav_total_nok"]) == Decimal(reference_result["nav_total_nok"])
        assert Decimal(worker_result["nav_per_share_nok"]) == Decimal(reference_result["nav_per_share_nok"])
        row = worker.connection.execute(
            """
            SELECT calculation_version,status,nav_scope
            FROM nav_snapshots
            WHERE as_of_at='2026-08-17T00:00:00Z' AND calculation_version=?
            """,
            (CORE_VERSION,),
        ).fetchone()
        assert tuple(row) == (CORE_VERSION, reference_result["status"], "CORE")
    finally:
        worker.connection.close()
        reference.connection.close()


def test_dirty_nav_writes_option_aware_full_nav_and_reconciles() -> None:
    repository = SqliteD1Repository()
    _seed(repository)
    try:
        result = asyncio.run(rebuild_dirty_nav(repository, as_of_date="2026-08-17"))
        assert result["status"] == "ok"
        assert result["ona"]["written"] == 1
        assert Decimal(result["ona"]["option_liability_nok"]) > 0

        core = repository.connection.execute(
            "SELECT nav_total_nok FROM nav_snapshots WHERE calculation_version=?",
            (CORE_VERSION,),
        ).fetchone()[0]
        full = repository.connection.execute(
            """
            SELECT nav_total_nok,other_net_assets_nok
            FROM nav_snapshots WHERE calculation_version=?
            """,
            (FULL_VERSION,),
        ).fetchone()
        assert Decimal(full[0]) == Decimal(core) + Decimal(full[1])
        assert Decimal(full[1]) == Decimal(result["ona"]["amount_nok"])

        option = repository.connection.execute(
            """
            SELECT option_liability_nok,option_quality
            FROM other_net_assets_daily_estimates
            WHERE estimate_date='2026-08-17'
            """
        ).fetchone()
        assert Decimal(option[0]) > 0
        assert option[1] == "FORECAST_MARK_TO_MARKET"
    finally:
        repository.connection.close()


def test_nav_date_resolution_uses_live_date_or_latest_otec() -> None:
    repository = SqliteD1Repository()
    _seed(repository)
    try:
        live = asyncio.run(
            resolve_nav_date(repository, target_date="2026-08-17", today="2026-08-17")
        )
        assert live == {
            "latest_otec_date": "2026-08-17",
            "live_calendar_snapshot": True,
            "nav_date": "2026-08-17",
        }
        historical = asyncio.run(
            resolve_nav_date(repository, target_date="2026-08-18", today="2026-08-18")
        )
        assert historical == {
            "latest_otec_date": "2026-08-17",
            "live_calendar_snapshot": False,
            "nav_date": "2026-08-17",
        }
    finally:
        repository.connection.close()

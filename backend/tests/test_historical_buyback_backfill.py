from decimal import Decimal

from app.buybacks import ingest_euronext_buyback_status
from app.buybacks.official_backfill import ZERO_PURCHASE_WEEKS, seed_known_official_buybacks
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history

SAMPLE = """
Reference is made to the stock exchange notice from 8 June 2026 announcing the
initiation of the share buyback program for Otello Corporation ASA (the Company).
From 6 July 2026 through 10 July 2026, Pareto Securities AS has bought 65,300
shares on behalf of the Company at an average price of NOK 17.11 and a total
value of NOK 1,117,133. Since the initiation of this share buyback program a
total of 332,882 shares at an average price of NOK 17.13 and a total value of
NOK 5,701,775 have been acquired. The maximum consideration to be paid for shares
acquired under this buyback program is NOK 20 per share and the maximum number of
shares that can be purchased under this buyback program is 2,192,046. At present
date, Otello owns 5,519,886 treasury shares in the Company, including those bought
in the previous buyback programs.
"""


def test_2025_official_backfill_starts_at_zero_and_reaches_december_cumulative(tmp_path) -> None:
    database = str(tmp_path / "history.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT b.trade_date, b.shares, b.amount_nok, b.cumulative_program_shares,
                   b.cumulative_program_amount_nok, b.treasury_shares_after, s.code AS source_code
            FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            JOIN source_documents sd ON sd.id = b.source_document_id
            JOIN sources s ON s.id = sd.source_id
            WHERE p.external_program_id = 'otec-buyback-2025-09-22'
            ORDER BY b.trade_date
            """
        ).fetchall()

    # Nine positive-purchase weeks. Two zero-purchase issuer statuses are retained in
    # ZERO_PURCHASE_WEEKS and do not create artificial buyback/cash rows.
    assert len(rows) == 9
    assert ZERO_PURCHASE_WEEKS == (
        ("2025-11-03", "2025-11-07", 1_039_642, Decimal("15428942")),
        ("2025-11-10", "2025-11-14", 1_039_642, Decimal("15428942")),
    )

    assert rows[0]["trade_date"] == "2025-09-26"
    assert rows[0]["shares"] == 159_500
    assert rows[0]["cumulative_program_shares"] == 159_500
    assert rows[0]["cumulative_program_amount_nok"] == "2273640"

    assert rows[-1]["trade_date"] == "2025-12-05"
    assert rows[-1]["cumulative_program_shares"] == 1_516_142
    assert rows[-1]["cumulative_program_amount_nok"] == "23997056"
    assert rows[-1]["treasury_shares_after"] == 1_516_142

    assert sum(row["shares"] for row in rows) == 1_516_142
    assert sum(Decimal(row["amount_nok"]) for row in rows) == Decimal("23997056")
    assert {row["source_code"] for row in rows} == {"EURONEXT"}


def test_official_source_replaces_mirror_without_double_counting_week(tmp_path) -> None:
    database = str(tmp_path / "precedence.db")
    init_database(database)
    seed_curated_history(database)

    ingest_euronext_buyback_status(
        text=SAMPLE,
        url="https://mfn.se/ob/a/otello/example-mirror",
        published_at="2026-07-11T21:49:44+02:00",
        database_path=database,
        source_code="MFN",
        source_metadata={"source_quality": "MIRROR", "upstream_source": "Oslo Bors"},
    )
    ingest_euronext_buyback_status(
        text=SAMPLE,
        url="https://live.euronext.com/en/products/equities/company-news/2026-07-11-otello-corporation-share-buyback-program-status",
        published_at="2026-07-11T21:49:44+02:00",
        database_path=database,
        source_code="EURONEXT",
        source_metadata={"source_quality": "CURATED_OFFICIAL"},
    )

    with get_connection(database) as connection:
        buybacks = connection.execute(
            """
            SELECT b.*, s.code AS source_code
            FROM buybacks b
            JOIN source_documents sd ON sd.id = b.source_document_id
            JOIN sources s ON s.id = sd.source_id
            """
        ).fetchall()
        cash = connection.execute(
            """
            SELECT cm.*, s.code AS source_code
            FROM cash_movements cm
            JOIN source_documents sd ON sd.id = cm.source_document_id
            JOIN sources s ON s.id = sd.source_id
            WHERE cm.movement_type = 'OTELLO_BUYBACK'
            """
        ).fetchall()
        share_rows = connection.execute(
            """
            SELECT osc.*, s.code AS source_code
            FROM otello_share_counts osc
            JOIN source_documents sd ON sd.id = osc.source_document_id
            JOIN sources s ON s.id = sd.source_id
            WHERE osc.effective_from = '2026-07-10'
              AND osc.notes LIKE 'Treasury shares from weekly %'
            """
        ).fetchall()

    assert len(buybacks) == 1
    assert len(cash) == 1
    assert len(share_rows) == 1
    assert buybacks[0]["source_code"] == "EURONEXT"
    assert cash[0]["source_code"] == "EURONEXT"
    assert share_rows[0]["source_code"] == "EURONEXT"
    assert buybacks[0]["shares"] == 65_300
    assert cash[0]["amount_nok"] == "-1117133"
    assert share_rows[0]["treasury_shares"] == 5_519_886

from decimal import Decimal

from app.buybacks import ingest_euronext_buyback_status, parse_euronext_buyback_status
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history

SAMPLE = """
Reference is made to the stock exchange notice from 8 June 2026 announcing the
initiation of the share buyback program for Otello Corporation ASA (the
Company). From 6 July 2026 through 10 July 2026, Pareto Securities AS has bought
65,300 shares on behalf of the Company at an average price of NOK 17.11 and a
total value of NOK 1,117,133. Since the initiation of this share buyback program
a total of 332,882 shares at an average price of NOK 17.13 and a total value of
NOK 5,701,775 have been acquired. The maximum consideration to be paid for
shares acquired under this buyback program is NOK 20 per share and the maximum
number of shares that can be purchased under this buyback program is 2,192,046.
At present date, Otello owns 5,519,886 treasury shares in the Company, including
those bought in the previous buyback programs.
"""


def test_parse_standard_euronext_buyback_status() -> None:
    item = parse_euronext_buyback_status(SAMPLE)
    assert item.program_reference_date == "2026-06-08"
    assert item.period_start == "2026-07-06"
    assert item.period_end == "2026-07-10"
    assert item.period_shares == 65_300
    assert item.period_avg_price_nok == Decimal("17.11")
    assert item.period_amount_nok == Decimal("1117133")
    assert item.cumulative_program_shares == 332_882
    assert item.cumulative_program_avg_price_nok == Decimal("17.13")
    assert item.cumulative_program_amount_nok == Decimal("5701775")
    assert item.max_program_shares == 2_192_046
    assert item.treasury_shares_after == 5_519_886
    assert item.program_external_id == "otec-buyback-2026-06-08"


def test_parser_fails_closed_when_financial_fields_are_missing() -> None:
    try:
        parse_euronext_buyback_status("Otello bought some shares this week.")
    except ValueError as exc:
        assert "mangler" in str(exc)
    else:
        raise AssertionError("Parser must fail instead of guessing")


def test_ingestion_updates_buyback_cash_and_share_count_idempotently(tmp_path) -> None:
    database = str(tmp_path / "buybacks.db")
    init_database(database)
    seed_curated_history(database)

    kwargs = dict(
        text=SAMPLE,
        url="https://live.euronext.com/en/products/equities/company-news/2026-07-11-otello-corporation-share-buyback-program-status",
        published_at="2026-07-11T21:49:00+02:00",
        database_path=database,
    )
    first = ingest_euronext_buyback_status(**kwargs)
    second = ingest_euronext_buyback_status(**kwargs)
    assert first["period_shares"] == second["period_shares"] == 65_300
    assert first["outstanding_shares_after"] == 73_790_829 - 5_519_886

    with get_connection(database) as connection:
        buyback = connection.execute("SELECT * FROM buybacks").fetchone()
        assert buyback["trade_date"] == "2026-07-10"
        assert buyback["shares"] == 65_300
        assert buyback["avg_price_nok"] == "17.11"
        assert buyback["amount_nok"] == "1117133"
        assert buyback["cumulative_program_shares"] == 332_882
        assert buyback["treasury_shares_after"] == 5_519_886

        cash = connection.execute(
            "SELECT * FROM cash_movements WHERE movement_type = 'OTELLO_BUYBACK'"
        ).fetchall()
        assert len(cash) == 1
        assert cash[0]["movement_date"] == "2026-07-10"
        assert cash[0]["amount_nok"] == "-1117133"
        assert cash[0]["confidence"] == "CONFIRMED"

        shares = connection.execute(
            """
            SELECT * FROM otello_share_counts
            WHERE effective_from = '2026-07-10'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        assert shares["total_shares"] == 73_790_829
        assert shares["treasury_shares"] == 5_519_886
        assert shares["outstanding_shares"] == 68_270_943

        assert connection.execute("SELECT COUNT(*) FROM buybacks").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM cash_movements WHERE movement_type = 'OTELLO_BUYBACK'"
        ).fetchone()[0] == 1

from decimal import Decimal

import pytest

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document
from app.nav.cash_curve import _known_movements
from app.newsweb.buyback_transactions import (
    DailyBuybackTransaction,
    parse_buyback_transaction_text,
    validate_daily_buybacks,
)
from app.newsweb.cash_sync import sync_newsweb_daily_buyback_cash
from app.newsweb.client import parse_list_payload, parse_message_payload
from app.buybacks.euronext import BuybackStatus


TRANSACTION_TEXT = """
B/S Symbol Qty Price Total consideration Date Time
B OTEC 100 17,20 1 720,00 30.06.2025 10:00:00
ExecBuy 100
AverageBuy 17,2000
ExecSell 0
AverageSell 0
B/S Symbol Qty Price Total consideration Date Time
B OTEC 50 17,30 865,00 01.07.2025 10:00:00
B OTEC 150 17,30 2 595,00 01.07.2025 11:00:00
ExecBuy 200
AverageBuy 17,3000
ExecSell 0
AverageSell 0
"""


def _weekly_status() -> BuybackStatus:
    return BuybackStatus(
        program_reference_date="2025-06-15",
        period_start="2025-06-30",
        period_end="2025-07-04",
        period_shares=300,
        period_avg_price_nok=Decimal("17.27"),
        period_amount_nok=Decimal("5180"),
        cumulative_program_shares=300,
        cumulative_program_avg_price_nok=Decimal("17.27"),
        cumulative_program_amount_nok=Decimal("5180"),
        max_program_shares=1_000_000,
        treasury_shares_after=1_000_300,
    )


def test_newsweb_transaction_text_aggregates_exact_daily_trades() -> None:
    rows = parse_buyback_transaction_text(TRANSACTION_TEXT)
    assert len(rows) == 2
    assert rows[0].trade_date == "2025-06-30"
    assert rows[0].shares == 100
    assert rows[0].amount_nok == Decimal("1720.00")
    assert rows[0].avg_price_nok == Decimal("17.20")
    assert rows[0].trade_count == 1
    assert rows[1].trade_date == "2025-07-01"
    assert rows[1].shares == 200
    assert rows[1].amount_nok == Decimal("3460.00")
    assert rows[1].avg_price_nok == Decimal("17.30")
    assert rows[1].trade_count == 2

    validation = validate_daily_buybacks(rows, _weekly_status())
    assert validation["shares"] == 300
    assert validation["amount_nok"] == "5180.00"
    assert validation["quality"] == "CONFIRMED"


def test_newsweb_parser_rejects_sell_or_broken_execbuy() -> None:
    with pytest.raises(ValueError, match="salg"):
        parse_buyback_transaction_text(
            "S OTEC 100 17,20 1 720,00 30.06.2025 10:00:00"
        )

    broken = TRANSACTION_TEXT.replace("ExecBuy 200", "ExecBuy 199")
    with pytest.raises(ValueError, match="ExecBuy-avstemming"):
        parse_buyback_transaction_text(broken)


def test_newsweb_message_and_list_payload_validate_otec() -> None:
    raw_message = {
        "messageId": 678028,
        "newsId": 630502,
        "title": "Otello Corporation share buyback program status",
        "body": "body",
        "issuerId": 7759,
        "issuerSign": "OTEC",
        "issuerName": "Otello Corporation ASA",
        "publishedTime": "2026-07-11T19:49:44.234Z",
        "markets": ["XOSL"],
        "category": [{"id": 1007}],
        "attachments": [{"id": 329535, "name": "OTEC Transaksjonsoversikt78.pdf"}],
        "correctedByMessageId": 0,
        "correctionForMessageId": 0,
        "clientAnnouncementId": "abc",
    }
    message = parse_message_payload({"data": {"message": raw_message}})
    assert message.message_id == 678028
    assert message.attachments[0].attachment_id == 329535
    assert message.public_url.endswith("/message/678028")

    list_row = {key: value for key, value in raw_message.items() if key not in {"body", "attachments"}}
    list_row["numbAttachments"] = 1
    messages, overflow = parse_list_payload(
        {"data": {"messages": [list_row], "overflow": False}}
    )
    assert overflow is False
    assert [item.message_id for item in messages] == [678028]

    bad = dict(raw_message)
    bad["issuerSign"] = "OTHER"
    with pytest.raises(ValueError, match="ikke OTEC"):
        parse_message_payload({"data": {"message": bad}})


def test_daily_newsweb_cash_replaces_weekly_summary_and_respects_anchor(tmp_path) -> None:
    db = str(tmp_path / "newsweb-cash.db")
    init_database(db)

    with get_connection(db) as connection:
        source_document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="newsweb-test-message",
            document_type="REGULATORY_NEWS_MIRROR",
            title="NewsWeb test",
            url="https://newsweb.oslobors.no/message/1",
        )
        attachment_document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="newsweb-test-attachment",
            document_type="BUYBACK_TRANSACTION_ATTACHMENT",
            title="transactions.pdf",
            url="https://api3.oslo.oslobors.no/v1/newsreader/attachment?messageId=1&attachmentId=2",
        )
        program_id = connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, max_shares,
                status, source_document_id
            ) VALUES ('test-program','2025-06-15T00:00:00Z','2025-06-15',1000000,'ACTIVE',?)
            """,
            (source_document_id,),
        ).lastrowid
        buyback_id = connection.execute(
            """
            INSERT INTO buybacks(
                program_id, trade_date, shares, avg_price_nok, amount_nok,
                cumulative_program_shares, treasury_shares_after, source_document_id
            ) VALUES (?, '2025-07-04', 300, '17.27', '5180', 300, 1000300, ?)
            """,
            (program_id, source_document_id),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, amount_original,
                currency, fx_rate_to_nok, description, source_document_id,
                confidence, buyback_id
            ) VALUES (
                '2025-07-04','OTELLO_BUYBACK','-5180','-5180','NOK','1',
                'Otello buyback: 300 shares during 2025-06-30–2025-07-04.',
                ?,'CONFIRMED',?
            )
            """,
            (source_document_id, buyback_id),
        )
        daily = [
            DailyBuybackTransaction("2025-06-30", 100, Decimal("17.20"), Decimal("1720"), 1),
            DailyBuybackTransaction("2025-07-01", 200, Decimal("17.30"), Decimal("3460"), 2),
        ]
        for item in daily:
            connection.execute(
                """
                INSERT INTO buyback_daily_transactions(
                    weekly_buyback_id, trade_date, shares, avg_price_nok, amount_nok,
                    trade_count, source_document_id, quality
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'CONFIRMED')
                """,
                (
                    buyback_id, item.trade_date, item.shares, str(item.avg_price_nok),
                    str(item.amount_nok), item.trade_count, attachment_document_id,
                ),
            )
        connection.commit()

        normalized = connection.execute(
            "SELECT document_type FROM source_documents WHERE id = ?",
            (source_document_id,),
        ).fetchone()["document_type"]
        assert normalized == "REGULATORY_NEWS"

    result = sync_newsweb_daily_buyback_cash(db, weekly_buyback_id=buyback_id)
    assert result["weeks_synced"] == 1
    assert result["weekly_cash_rows_deleted"] == 1
    assert result["daily_cash_rows_written"] == 2

    with get_connection(db) as connection:
        weekly_count = connection.execute(
            "SELECT COUNT(*) n FROM cash_movements WHERE movement_type='OTELLO_BUYBACK'"
        ).fetchone()["n"]
        assert weekly_count == 0
        daily_cash = connection.execute(
            """
            SELECT movement_date, amount_nok FROM cash_movements
            WHERE movement_type='OTELLO_BUYBACK_DAILY'
            ORDER BY movement_date
            """
        ).fetchall()
        assert [(row["movement_date"], row["amount_nok"]) for row in daily_cash] == [
            ("2025-06-30", "-1720"),
            ("2025-07-01", "-3460"),
        ]

        # A 30 June reported cash anchor already includes the 30 June trade. The normal
        # cash query is start-exclusive, so only the 1 July transaction is post-anchor.
        movements = _known_movements(connection, "2025-06-30", "2025-12-31")
        buyback_movements = [
            item for item in movements if item["movement_type"] == "OTELLO_BUYBACK_DAILY"
        ]
        assert len(buyback_movements) == 1
        assert buyback_movements[0]["movement_date"] == "2025-07-01"
        assert buyback_movements[0]["amount_nok"] == "-3460"

        # A later legacy collector cannot recreate the weekly cash summary after daily
        # transaction detail exists; migration trigger silently ignores it.
        connection.execute(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, currency, description, confidence
            ) VALUES ('2025-07-04','OTELLO_BUYBACK','-5180','NOK','legacy retry','CONFIRMED')
            """
        )
        assert connection.execute(
            "SELECT COUNT(*) n FROM cash_movements WHERE movement_type='OTELLO_BUYBACK'"
        ).fetchone()["n"] == 0

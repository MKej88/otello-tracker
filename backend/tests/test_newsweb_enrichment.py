from decimal import Decimal

import pytest

from app.buybacks.euronext import parse_euronext_buyback_status
from app.newsweb.enrichment import (
    _normalize_weekly_body,
    parse_buyback_transaction_text,
)


def test_legacy_2024_weekly_wording_normalizes_to_strict_parser() -> None:
    body = (
        "Reference is made to the stock exchange notice from 22 July 2024 announcing a share buyback program "
        "for Otello Corporation ASA (the Company). From 22 July 2024 through 26 July 2024, Pareto Securities AS "
        "has bought 56,000 shares on behalf of the Company at an average price of NOK 7.90 and a total value of "
        "NOK 442,353. Since the initiation of the share buyback program a total of 56,000 shares at an average "
        "price of NOK 7.90 and a total value of NOK 442,353 have been acquired. The maximum consideration to be "
        "paid for shares acquired under the buyback program is NOK 15 per share and the maximum number of shares "
        "that can be purchased is 4,554,986 shares (5% of total outstanding shares). At present date, Otello owns "
        "3,744,364 treasury shares in the Company."
    )
    parsed = parse_euronext_buyback_status(_normalize_weekly_body(body))
    assert parsed.program_reference_date == "2024-07-22"
    assert parsed.period_end == "2024-07-26"
    assert parsed.period_shares == 56_000
    assert parsed.period_amount_nok == Decimal("442353")


def test_weekly_decimal_comma_average_is_not_scaled_100x() -> None:
    body = (
        "Reference is made to the stock exchange notice from 16 June 2025 announcing the initiation of the share "
        "buyback program for Otello Corporation ASA (the Company). From 14 July 2025 through 18 July 2025, Pareto "
        "Securities AS has bought 662,600 shares on behalf of the Company at an average price of NOK 13,17 and a "
        "total value of NOK 8,725,420. Since the initiation of this share buyback program a total of 2,828,800 shares "
        "at an average price of NOK 12.49 and a total value of NOK 35,320,824 have been acquired. The maximum number "
        "of shares that can be purchased under this buyback program is 5,047,130. At present date, Otello owns "
        "5,980,620 treasury shares in the Company."
    )
    parsed = parse_euronext_buyback_status(_normalize_weekly_body(body))
    assert parsed.period_avg_price_nok == Decimal("13.17")


def test_legacy_pdf_glued_date_time_parses() -> None:
    text = """
B/S Symbol Qty Price Total consideration Date Time
B OTEC 1 741 7,8800 13 719,08 22.07.202409:25:51
B OTEC 259 7,9000 2 046,10 22.07.202409:26:23
ExecBuy 2 000
AverageBuy 7,8826
ExecSell 0
AverageSell 0
"""
    rows = parse_buyback_transaction_text(text)
    assert len(rows) == 1
    assert rows[0].trade_date == "2024-07-22"
    assert rows[0].shares == 2_000
    assert rows[0].amount_nok == Decimal("15765.18")


def test_new_pdf_time_before_date_and_integer_price_parses() -> None:
    text = """
B/S Symbol Qty Price Total ConsiderationTime Date
B OTEC 4 063 16,92 68 745,9616:06:4627.07.2026
B OTEC 462 16,9 7 807,8015:01:2027.07.2026
ExecBuy 4 525
AverageBuy 16,9180
ExecSell 0
AverageSell 0
B/S Symbol Qty Price Total ConsiderationTime Date
B OTEC 3 120 17 53 040 09:56:1831.07.2026
B OTEC 4 880 17 82 960 09:40:5131.07.2026
ExecBuy 8 000
AverageBuy 17
ExecSell 0
AverageSell 0
"""
    rows = parse_buyback_transaction_text(text)
    assert [row.trade_date for row in rows] == ["2026-07-27", "2026-07-31"]
    assert [row.shares for row in rows] == [4_525, 8_000]
    assert rows[1].amount_nok == Decimal("136000")


def test_execbuy_block_order_can_differ_from_date_order() -> None:
    text = """
B/S Symbol Qty Price Total consideration Date Time
B OTEC 100 18,00 1 800,00 28.05.2026 10:00:00
ExecBuy 100
B/S Symbol Qty Price Total consideration Date Time
B OTEC 200 18,00 3 600,00 27.05.2026 10:00:00
ExecBuy 200
"""
    rows = parse_buyback_transaction_text(text)
    assert [row.trade_date for row in rows] == ["2026-05-27", "2026-05-28"]
    assert [row.shares for row in rows] == [200, 100]



def _missing_date_pdf_text() -> str:
    return """
B/S Symbol Qty Price Total Consideration Time Date
B OTEC 13 000 17,00 221 000,00 10:00:00 17.08.2026
ExecBuy 13 000
B/S Symbol Qty Price Total Consideration Time Date
B OTEC 13 000 17,00 221 000,00 10:00:00 18.08.2026
ExecBuy 13 000
B/S Symbol Qty Price Total Consideration Time Date
B OTEC 12 000 17,00 204 000,00 10:00:00 19.08.2026
ExecBuy 12 000
B/S Symbol Qty Price Total Consideration Time Date
B OTEC 13 000 17,00 221 000,00 10:00:00 20.08.2026
ExecBuy 13 000
B/S Symbol Qty Price Total Consideration Time Date
B OTEC 8 000 17,00 136 000,00 10:42:30 10:42:30
B OTEC 5 000 17,00 85 000,00 10:14:00 10:14:00
ExecBuy 13 000
"""


def test_duplicate_time_missing_date_recovers_only_unambiguous_weekday() -> None:
    rows = parse_buyback_transaction_text(
        _missing_date_pdf_text(),
        period_start="2026-08-17",
        period_end="2026-08-21",
    )
    assert [row.trade_date for row in rows] == [
        "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"
    ]
    assert [row.shares for row in rows] == [13_000, 13_000, 12_000, 13_000, 13_000]


def test_duplicate_time_missing_date_stays_fail_closed_when_period_is_ambiguous() -> None:
    with pytest.raises(ValueError, match="entydig"):
        parse_buyback_transaction_text(
            _missing_date_pdf_text(),
            period_start="2026-08-17",
            period_end="2026-08-24",
        )


def test_duplicate_time_missing_date_without_weekly_context_stays_fail_closed() -> None:
    with pytest.raises(ValueError, match="ExecBuy-avstemming"):
        parse_buyback_transaction_text(_missing_date_pdf_text())

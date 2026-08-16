from __future__ import annotations

from decimal import Decimal

from app.buybacks.euronext import BuybackStatus


MARCH_2022_BUYBACK = {
    "published_at": "2022-03-28T07:30:00+02:00",
    "url": "https://news.cision.com/otello-corporation-asa/r/completion-of-share-buyback-offer,c3533188",
    "source_code": "OTELLO_IR",
    "source_note": (
        "Issuer release distributed by Cision: Otello completed the shareholder-wide "
        "bookbuilding on 28 March 2022 and acquired 10,000,000 shares at NOK 27.50 per "
        "share, for exact consideration of NOK 275,000,000. The 1H22 report independently "
        "confirms 10.00 million shares bought for USD 31.2 million."
    ),
    "status": BuybackStatus(
        program_reference_date="2022-03-21",
        period_start="2022-03-28",
        period_end="2022-03-28",
        period_shares=10_000_000,
        period_avg_price_nok=Decimal("27.5"),
        period_amount_nok=Decimal("275000000"),
        cumulative_program_shares=10_000_000,
        cumulative_program_avg_price_nok=Decimal("27.5"),
        cumulative_program_amount_nok=Decimal("275000000"),
        max_program_shares=10_000_000,
        treasury_shares_after=10_000_000,
    ),
}


OLDER_2022_OFFICIAL_BUYBACKS = [MARCH_2022_BUYBACK]

from decimal import Decimal

from app.buybacks.euronext import parse_euronext_buyback_status
from app.newsweb.normalization import normalize_weekly_body


def test_february_2025_continuation_wording_normalizes() -> None:
    body = (
        "Reference is made to the stock exchange notice from 3 February 2025 announcing "
        "the continuation of the share buyback program for Otello Corporation ASA (the Company). "
        "From 10 February 2025 through 14 February 2025, Pareto Securities AS has bought "
        "346,900 shares on behalf of the Company at an average price of NOK 7.58 and a total value "
        "of NOK 2,631,058. Since the initiation of this continuation of the share buyback program "
        "a total of 649,900 shares at an average price of NOK 7.59 and a total value of NOK 4,933,848 "
        "have been acquired. The maximum consideration to be paid for shares acquired under this "
        "buyback program is NOK 15 per share and the maximum number of shares that can be purchased "
        "under this continuation of the buyback program is 866,690 shares (being the maximum remaining "
        "number of outstanding shares that can be purchased under the existing authorization). At "
        "present date, Otello owns 8,893,160 treasury shares in the Company."
    )
    parsed = parse_euronext_buyback_status(normalize_weekly_body(body))
    assert parsed.program_reference_date == "2025-02-03"
    assert parsed.period_start == "2025-02-10"
    assert parsed.period_end == "2025-02-14"
    assert parsed.period_shares == 346_900
    assert parsed.period_avg_price_nok == Decimal("7.58")
    assert parsed.period_amount_nok == Decimal("2631058")
    assert parsed.cumulative_program_shares == 649_900
    assert parsed.max_program_shares == 866_690
    assert parsed.treasury_shares_after == 8_893_160

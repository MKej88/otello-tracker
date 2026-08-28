from decimal import Decimal

import pytest

from app.newsweb.normalization import normalize_weekly_body
from app.newsweb.weekly_parser import parse_newsweb_weekly_status


FIRST_WEEK_2023 = """
Reference is made to the stock exchange notices from 20 June 2023 announcing the initiation
of the share buyback program for Otello Corporation ASA (the Company). From 20 June 2023
through 23 June 2023, Pareto Securities AS has bought 99,087 shares on the behalf of the
Company at an average price of NOK 8.49 and a total value of NOK 841,269. The maximum
consideration to be paid for shares acquired under the buyback program is NOK 15 per share
and the maximum number of shares that can be purchased under this buyback program is
4 554 986 shares (5% of total outstanding shares).
"""

TYPO_WEEK_2023 = """
Reference is made to the stock exchange notices from 20 June 2023 announcing the initiation
of the share buyback program for Otello Corporation ASA (the Company). From 26 June 2023
through 30 June 2023, Pareto Securities AS has bought 182,642 shares on the behalf of the
Company at an average price of NOK 8.03 and a total value of NOK 1,466,062. Sine the
initiation of the share buyback program a total of 281,729 shares at an average price of NOK
8.19 and a total value of NOK 2,307,331 have been acquired. The maximum consideration to
be paid for shares acquired under the buyback program is NOK 15 per share and the maximum
number of shares that can be purchased under this buyback program is 4,554,986 shares.
At present date, Otello owns 281,729 treasury shares in the Company.
"""


def test_documented_sine_typo_normalizes_without_changing_values() -> None:
    normalized = normalize_weekly_body(TYPO_WEEK_2023)
    assert "Sine the initiation" not in normalized
    assert "Since the initiation of this share buyback program" in normalized
    parsed = parse_newsweb_weekly_status(TYPO_WEEK_2023)
    assert parsed.program_reference_date == "2023-06-20"
    assert parsed.period_end == "2023-06-30"
    assert parsed.period_shares == 182_642
    assert parsed.period_amount_nok == Decimal("1466062")
    assert parsed.cumulative_program_shares == 281_729
    assert parsed.treasury_shares_after == 281_729


def test_first_program_week_can_infer_only_missing_cumulative_and_treasury() -> None:
    parsed = parse_newsweb_weekly_status(FIRST_WEEK_2023)
    assert parsed.program_reference_date == parsed.period_start == "2023-06-20"
    assert parsed.period_end == "2023-06-23"
    assert parsed.period_shares == 99_087
    assert parsed.period_avg_price_nok == Decimal("8.49")
    assert parsed.period_amount_nok == Decimal("841269")
    assert parsed.cumulative_program_shares == parsed.period_shares
    assert parsed.cumulative_program_amount_nok == parsed.period_amount_nok
    assert parsed.treasury_shares_after == parsed.period_shares
    assert parsed.max_program_shares == 4_554_986


def test_first_week_fallback_refuses_non_starting_period() -> None:
    altered = FIRST_WEEK_2023.replace("From 20 June 2023", "From 21 June 2023")
    try:
        parse_newsweb_weekly_status(altered)
    except ValueError as exc:
        assert "mangler" in str(exc)
    else:
        raise AssertionError("Legacy fallback must not infer cumulative values mid-program")


def test_first_week_parser_reports_unknown_month_as_invalid_input() -> None:
    malformed = FIRST_WEEK_2023.replace("20 June 2023", "20 Juny 2023")

    with pytest.raises(ValueError, match="Ugyldig NewsWeb-buybackdato"):
        parse_newsweb_weekly_status(malformed)

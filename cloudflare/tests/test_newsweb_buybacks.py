from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from newsweb_buybacks import parse_newsweb_weekly_status  # noqa: E402


def test_first_program_week_keeps_reported_treasury_share_total() -> None:
    message = """
    The stock exchange notice from 1 August 2026 announcing the initiation of the
    share buyback program. From 1 August 2026 through 7 August 2026, Otello has
    bought 100 shares at an average price of NOK 20.00 and a total value of NOK
    2,000. The maximum number of shares that can be purchased under this buyback
    program is 1,000. At present date, Otello owns 350 treasury shares.
    """

    parsed = parse_newsweb_weekly_status(message)

    assert parsed.period_shares == 100
    assert parsed.treasury_shares_after == 350

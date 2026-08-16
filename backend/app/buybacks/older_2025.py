from __future__ import annotations

from decimal import Decimal

from app.buybacks.euronext import BuybackStatus

EURONEXT_NEWS = "https://live.euronext.com/en/products/equities/company-news"


def _entry(
    *,
    release_date: str,
    published_at: str,
    program_date: str,
    period_start: str,
    period_end: str,
    shares: int,
    avg: str,
    amount: str,
    cumulative_shares: int,
    cumulative_avg: str,
    cumulative_amount: str,
    max_shares: int,
    treasury: int,
    source_note: str | None = None,
) -> dict:
    return {
        "published_at": published_at,
        "url": f"{EURONEXT_NEWS}/{release_date}-otello-corporation-share-buyback-program-status",
        "source_note": source_note,
        "status": BuybackStatus(
            program_reference_date=program_date,
            period_start=period_start,
            period_end=period_end,
            period_shares=shares,
            period_avg_price_nok=Decimal(avg),
            period_amount_nok=Decimal(amount),
            cumulative_program_shares=cumulative_shares,
            cumulative_program_avg_price_nok=Decimal(cumulative_avg),
            cumulative_program_amount_nok=Decimal(cumulative_amount),
            max_program_shares=max_shares,
            treasury_shares_after=treasury,
        ),
    }


# Program initiated 7 April 2025. All rows are structured transcriptions of the
# original Euronext / Oslo Bors Newspoint weekly status releases.
APRIL_2025_PROGRAM = [
    _entry(
        release_date="2025-04-11", published_at="2025-04-11T22:00:00+02:00",
        program_date="2025-04-07", period_start="2025-04-07", period_end="2025-04-11",
        shares=709_400, avg="8.46", amount="6001694",
        cumulative_shares=709_400, cumulative_avg="8.46", cumulative_amount="6001694",
        max_shares=3_688_364, treasury=709_400,
    ),
    _entry(
        release_date="2025-04-17", published_at="2025-04-17T22:00:00+02:00",
        program_date="2025-04-07", period_start="2025-04-14", period_end="2025-04-17",
        shares=334_920, avg="8.99", amount="3011798",
        cumulative_shares=1_044_320, cumulative_avg="8.63", cumulative_amount="9013492",
        max_shares=3_688_364, treasury=1_044_320,
    ),
    _entry(
        release_date="2025-04-25", published_at="2025-04-25T22:00:00+02:00",
        program_date="2025-04-07", period_start="2025-04-22", period_end="2025-04-25",
        shares=458_500, avg="9.05", amount="4150714",
        cumulative_shares=1_502_820, cumulative_avg="8.76", cumulative_amount="13164206",
        max_shares=3_688_364, treasury=1_502_820,
    ),
    _entry(
        release_date="2025-05-02", published_at="2025-05-02T22:00:00+02:00",
        program_date="2025-04-07", period_start="2025-04-28", period_end="2025-05-02",
        shares=398_800, avg="9.55", amount="3807589",
        cumulative_shares=1_901_620, cumulative_avg="8.92", cumulative_amount="16971795",
        max_shares=3_688_364, treasury=1_901_620,
    ),
    _entry(
        release_date="2025-05-11", published_at="2025-05-11T22:00:00+02:00",
        program_date="2025-04-07", period_start="2025-05-05", period_end="2025-05-09",
        shares=448_600, avg="9.99", amount="4481886",
        cumulative_shares=2_350_220, cumulative_avg="9.13", cumulative_amount="21453681",
        max_shares=3_688_364, treasury=2_350_220,
    ),
    _entry(
        release_date="2025-05-16", published_at="2025-05-16T22:00:00+02:00",
        program_date="2025-04-07", period_start="2025-05-12", period_end="2025-05-16",
        shares=379_500, avg="10.79", amount="4095400",
        cumulative_shares=2_729_720, cumulative_avg="9.36", cumulative_amount="25549082",
        max_shares=3_688_364, treasury=2_729_720,
    ),
    _entry(
        release_date="2025-05-23", published_at="2025-05-23T22:00:00+02:00",
        program_date="2025-04-07", period_start="2025-05-19", period_end="2025-05-23",
        shares=422_100, avg="10.45", amount="4410701",
        cumulative_shares=3_151_820, cumulative_avg="9.50", cumulative_amount="29956543",
        max_shares=3_688_364, treasury=3_151_820,
    ),
]


# Program initiated 16 June 2025 and completed 19 August 2025. Treasury counts include
# the 3,151,820 shares retained from the preceding April program.
JUNE_2025_PROGRAM = [
    _entry(
        release_date="2025-06-20", published_at="2025-06-20T22:12:00+02:00",
        program_date="2025-06-16", period_start="2025-06-16", period_end="2025-06-20",
        shares=500_600, avg="11.92", amount="5968177",
        cumulative_shares=500_600, cumulative_avg="11.92", cumulative_amount="5968177",
        max_shares=5_047_130, treasury=3_652_420,
    ),
    _entry(
        release_date="2025-06-27", published_at="2025-06-27T21:36:00+02:00",
        program_date="2025-06-16", period_start="2025-06-23", period_end="2025-06-27",
        shares=510_900, avg="11.96", amount="6109297",
        cumulative_shares=1_011_500, cumulative_avg="11.94", cumulative_amount="12077474",
        max_shares=5_047_130, treasury=4_163_320,
    ),
    _entry(
        release_date="2025-07-04", published_at="2025-07-04T21:55:00+02:00",
        program_date="2025-06-16", period_start="2025-06-30", period_end="2025-07-04",
        shares=513_000, avg="12.19", amount="6250920",
        cumulative_shares=1_524_500, cumulative_avg="12.02", cumulative_amount="18328394",
        max_shares=5_047_130, treasury=4_676_320,
        source_note=(
            "Weekly status spans the 30 June 2025 reporting date. For daily cash, the full "
            "weekly cash outflow is recorded at period end unless transaction-level attachment "
            "data is later imported; the 30 June cash anchor still reconciles the historical curve."
        ),
    ),
    _entry(
        release_date="2025-07-13", published_at="2025-07-13T23:26:00+02:00",
        program_date="2025-06-16", period_start="2025-07-07", period_end="2025-07-11",
        shares=641_700, avg="12.88", amount="8267010",
        cumulative_shares=2_166_200, cumulative_avg="12.28", cumulative_amount="26595404",
        max_shares=5_047_130, treasury=5_318_020,
    ),
    _entry(
        release_date="2025-07-18", published_at="2025-07-18T22:00:00+02:00",
        program_date="2025-06-16", period_start="2025-07-14", period_end="2025-07-18",
        shares=662_600, avg="13.17", amount="8725420",
        cumulative_shares=2_828_800, cumulative_avg="12.49", cumulative_amount="35320824",
        max_shares=5_047_130, treasury=5_980_620,
    ),
    _entry(
        release_date="2025-07-25", published_at="2025-07-25T22:00:00+02:00",
        program_date="2025-06-16", period_start="2025-07-21", period_end="2025-07-25",
        shares=720_830, avg="13.59", amount="9798210",
        cumulative_shares=3_549_630, cumulative_avg="12.71", cumulative_amount="45119034",
        max_shares=5_047_130, treasury=6_701_450,
    ),
    _entry(
        release_date="2025-08-01", published_at="2025-08-01T22:00:00+02:00",
        program_date="2025-06-16", period_start="2025-07-28", period_end="2025-08-01",
        shares=615_198, avg="13.49", amount="8296157",
        cumulative_shares=4_164_828, cumulative_avg="12.83", cumulative_amount="53415191",
        max_shares=5_047_130, treasury=7_316_648,
    ),
    _entry(
        release_date="2025-08-08", published_at="2025-08-08T22:00:00+02:00",
        program_date="2025-06-16", period_start="2025-08-04", period_end="2025-08-08",
        shares=436_223, avg="13.26", amount="5784040",
        cumulative_shares=4_601_051, cumulative_avg="12.87", cumulative_amount="59199230",
        max_shares=5_047_130, treasury=7_752_871,
    ),
    _entry(
        release_date="2025-08-15", published_at="2025-08-15T22:24:00+02:00",
        program_date="2025-06-16", period_start="2025-08-11", period_end="2025-08-15",
        shares=348_336, avg="13.18", amount="4592086",
        cumulative_shares=4_949_387, cumulative_avg="12.89", cumulative_amount="63791317",
        max_shares=5_047_130, treasury=8_101_207,
    ),
    _entry(
        release_date="2025-08-23", published_at="2025-08-23T22:12:00+02:00",
        program_date="2025-06-16", period_start="2025-08-18", period_end="2025-08-19",
        shares=97_743, avg="13.54", amount="1323562",
        cumulative_shares=5_047_130, cumulative_avg="12.90", cumulative_amount="65114879",
        max_shares=5_047_130, treasury=8_198_950,
    ),
]


OLDER_2025_OFFICIAL_BUYBACKS = APRIL_2025_PROGRAM + JUNE_2025_PROGRAM

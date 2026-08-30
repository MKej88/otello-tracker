from __future__ import annotations

from decimal import Decimal

from app.buybacks.euronext import BuybackStatus

EURONEXT_NEWS = "https://live.euronext.com/en/products/equities/company-news"


def _entry(
    *,
    release_date: str,
    period_start: str,
    period_end: str,
    shares: int,
    avg: str,
    amount: str,
    cumulative_shares: int,
    cumulative_avg: str,
    cumulative_amount: str,
    source_note: str | None = None,
) -> dict:
    return {
        "published_at": f"{release_date}T00:00:00Z",
        "url": f"{EURONEXT_NEWS}/{release_date}-otello-corporation-share-buyback-program-status",
        "source_note": source_note,
        "status": BuybackStatus(
            program_reference_date="2023-06-20",
            period_start=period_start,
            period_end=period_end,
            period_shares=shares,
            period_avg_price_nok=Decimal(avg),
            period_amount_nok=Decimal(amount),
            cumulative_program_shares=cumulative_shares,
            cumulative_program_avg_price_nok=Decimal(cumulative_avg),
            cumulative_program_amount_nok=Decimal(cumulative_amount),
            max_program_shares=4_554_986,
            treasury_shares_after=cumulative_shares,
        ),
    }


# Structured transcriptions of the Euronext / Oslo Bors Newspoint status releases
# for the share buyback program initiated 20 June 2023. Raw issuer weekly figures
# are preserved here. Small rounding inconsistencies against the issuer's cumulative
# NOK control totals are reconciled only in older_2023_reconciled.py.
CALENDAR_2023_PROGRAM = [
    _entry(
        release_date="2023-06-26", period_start="2023-06-20", period_end="2023-06-23",
        shares=99_087, avg="8.49", amount="841269",
        cumulative_shares=99_087, cumulative_avg="8.49", cumulative_amount="841269",
    ),
    _entry(
        release_date="2023-07-03", period_start="2023-06-26", period_end="2023-06-30",
        shares=182_642, avg="8.03", amount="1466062",
        cumulative_shares=281_729, cumulative_avg="8.19", cumulative_amount="2307331",
    ),
    _entry(
        release_date="2023-07-10", period_start="2023-07-03", period_end="2023-07-07",
        shares=286_627, avg="8.23", amount="2359639",
        cumulative_shares=568_356, cumulative_avg="8.21", cumulative_amount="4666969",
    ),
    _entry(
        release_date="2023-07-17", period_start="2023-07-10", period_end="2023-07-14",
        shares=446_900, avg="8.64", amount="3861673",
        cumulative_shares=1_015_256, cumulative_avg="8.40", cumulative_amount="8528643",
    ),
    _entry(
        release_date="2023-07-24", period_start="2023-07-17", period_end="2023-07-21",
        shares=335_247, avg="8.88", amount="2976591",
        cumulative_shares=1_350_503, cumulative_avg="8.52", cumulative_amount="11505234",
    ),
    _entry(
        release_date="2023-07-31", period_start="2023-07-24", period_end="2023-07-28",
        shares=407_604, avg="9.34", amount="3805344",
        cumulative_shares=1_758_107, cumulative_avg="8.71", cumulative_amount="15310578",
    ),
    _entry(
        release_date="2023-08-07", period_start="2023-07-31", period_end="2023-08-04",
        shares=331_443, avg="9.33", amount="3091438",
        cumulative_shares=2_089_550, cumulative_avg="8.81", cumulative_amount="18402026",
    ),
    _entry(
        release_date="2023-08-14", period_start="2023-08-07", period_end="2023-08-11",
        shares=134_406, avg="9.21", amount="1237510",
        cumulative_shares=2_223_956, cumulative_avg="8.83", cumulative_amount="19639527",
    ),
    _entry(
        release_date="2023-08-21", period_start="2023-08-14", period_end="2023-08-18",
        shares=96_349, avg="8.76", amount="843911",
        cumulative_shares=2_320_305, cumulative_avg="8.83", cumulative_amount="20483437",
    ),
    _entry(
        release_date="2023-08-28", period_start="2023-08-21", period_end="2023-08-25",
        shares=68_362, avg="8.46", amount="578280",
        cumulative_shares=2_388_667, cumulative_avg="8.82", cumulative_amount="21061717",
    ),
    _entry(
        release_date="2023-09-04", period_start="2023-08-28", period_end="2023-09-01",
        shares=66_055, avg="8.31", amount="549053",
        cumulative_shares=2_454_722, cumulative_avg="8.80", cumulative_amount="21610770",
    ),
    _entry(
        release_date="2023-09-11", period_start="2023-09-04", period_end="2023-09-08",
        shares=51_352, avg="8.33", amount="427894",
        cumulative_shares=2_506_074, cumulative_avg="8.79", cumulative_amount="22038664",
    ),
    _entry(
        release_date="2023-09-18", period_start="2023-09-11", period_end="2023-09-15",
        shares=15_957, avg="8.26", amount="131731",
        cumulative_shares=2_522_031, cumulative_avg="8.79", cumulative_amount="22170394",
    ),
    _entry(
        release_date="2023-09-25", period_start="2023-09-18", period_end="2023-09-22",
        shares=32_753, avg="8.19", amount="268176",
        cumulative_shares=2_554_784, cumulative_avg="8.78", cumulative_amount="22438570",
    ),
    _entry(
        release_date="2023-10-02", period_start="2023-09-25", period_end="2023-09-29",
        shares=41_769, avg="7.90", amount="329798",
        cumulative_shares=2_596_553, cumulative_avg="8.77", cumulative_amount="22768368",
    ),
    _entry(
        release_date="2023-10-09", period_start="2023-10-02", period_end="2023-10-06",
        shares=41_532, avg="7.77", amount="322576",
        cumulative_shares=2_638_085, cumulative_avg="8.75", cumulative_amount="23090944",
    ),
    _entry(
        release_date="2023-10-16", period_start="2023-10-09", period_end="2023-10-13",
        shares=50_832, avg="7.77", amount="394937",
        cumulative_shares=2_688_917, cumulative_avg="8.73", cumulative_amount="23485881",
    ),
    _entry(
        release_date="2023-10-23", period_start="2023-10-16", period_end="2023-10-20",
        shares=55_322, avg="7.71", amount="426469",
        cumulative_shares=2_744_239, cumulative_avg="8.71", cumulative_amount="23912350",
    ),
    _entry(
        release_date="2023-10-30", period_start="2023-10-23", period_end="2023-10-27",
        shares=51_279, avg="7.48", amount="383494",
        cumulative_shares=2_795_518, cumulative_avg="8.69", cumulative_amount="24295842",
    ),
    _entry(
        release_date="2023-11-06", period_start="2023-10-30", period_end="2023-11-03",
        shares=63_756, avg="7.49", amount="477451",
        cumulative_shares=2_859_274, cumulative_avg="8.66", cumulative_amount="24773294",
    ),
    _entry(
        release_date="2023-11-13", period_start="2023-11-06", period_end="2023-11-10",
        shares=71_155, avg="7.66", amount="545103",
        cumulative_shares=2_930_429, cumulative_avg="8.64", cumulative_amount="25318397",
    ),
    _entry(
        release_date="2023-11-20", period_start="2023-11-13", period_end="2023-11-17",
        shares=70_937, avg="7.91", amount="560860",
        cumulative_shares=3_001_366, cumulative_avg="8.62", cumulative_amount="25879257",
    ),
    _entry(
        release_date="2023-11-27", period_start="2023-11-20", period_end="2023-11-24",
        shares=64_923, avg="7.95", amount="516134",
        cumulative_shares=3_066_289, cumulative_avg="8.61", cumulative_amount="26395390",
    ),
    _entry(
        release_date="2023-12-06", period_start="2023-11-27", period_end="2023-12-05",
        shares=36_988, avg="7.71", amount="285271",
        cumulative_shares=3_103_277, cumulative_avg="8.60", cumulative_amount="26680662",
    ),
    _entry(
        release_date="2023-12-11", period_start="2023-12-06", period_end="2023-12-08",
        shares=18_048, avg="7.65", amount="138108",
        cumulative_shares=3_121_325, cumulative_avg="8.59", cumulative_amount="26818770",
    ),
    _entry(
        release_date="2023-12-18", period_start="2023-12-11", period_end="2023-12-15",
        shares=26_172, avg="7.96", amount="208336",
        cumulative_shares=3_147_497, cumulative_avg="8.59", cumulative_amount="27027106",
    ),
    _entry(
        release_date="2023-12-27", period_start="2023-12-18", period_end="2023-12-22",
        shares=21_221, avg="8.11", amount="172163",
        cumulative_shares=3_168_718, cumulative_avg="8.58", cumulative_amount="27199269",
    ),
    _entry(
        release_date="2024-01-01", period_start="2023-12-27", period_end="2023-12-29",
        shares=11_309, avg="8.10", amount="91630",
        cumulative_shares=3_180_027, cumulative_avg="8.58", cumulative_amount="27290898",
        source_note=(
            "The 1 Jan 2024 Euronext page renders the period start as '237December 2023'. "
            "The attached transaction overview and calendar sequence resolve the intended "
            "date as 27 December 2023."
        ),
    ),
]


OLDER_2023_OFFICIAL_BUYBACKS = CALENDAR_2023_PROGRAM

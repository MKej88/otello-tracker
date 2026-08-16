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


# Program initiated 22 July 2024. These are structured transcriptions of the original
# Euronext / Oslo Bors Newspoint weekly status releases. Raw issuer inconsistencies are
# intentionally preserved here and reconciled only in older_2024_reconciled.py.
JULY_2024_PROGRAM = [
    _entry(
        release_date="2024-07-28", published_at="2024-07-28T21:55:00+02:00",
        program_date="2024-07-22", period_start="2024-07-22", period_end="2024-07-26",
        shares=56_000, avg="7.90", amount="442353",
        cumulative_shares=56_000, cumulative_avg="7.90", cumulative_amount="442353",
        max_shares=4_554_986, treasury=3_744_364,
    ),
    _entry(
        release_date="2024-08-02", published_at="2024-08-02T21:35:00+02:00",
        program_date="2024-07-22", period_start="2024-07-29", period_end="2024-08-02",
        shares=75_600, avg="7.91", amount="598278",
        cumulative_shares=131_600, cumulative_avg="7.91", cumulative_amount="1040631",
        max_shares=4_554_986, treasury=3_819_964,
    ),
    _entry(
        release_date="2024-08-11", published_at="2024-08-11T15:51:00+02:00",
        program_date="2024-07-22", period_start="2024-08-05", period_end="2024-08-09",
        shares=122_600, avg="7.68", amount="941433",
        cumulative_shares=254_200, cumulative_avg="7.80", cumulative_amount="1982064",
        max_shares=4_554_986, treasury=4_074_164,
    ),
    _entry(
        release_date="2024-08-19", published_at="2024-08-19T00:50:00+02:00",
        program_date="2024-07-22", period_start="2024-08-12", period_end="2024-08-16",
        shares=303_300, avg="7.86", amount="2384231",
        cumulative_shares=557_500, cumulative_avg="7.83", cumulative_amount="4366294",
        max_shares=4_554_986, treasury=4_245_864,
    ),
    _entry(
        release_date="2024-08-25", published_at="2024-08-25T18:45:00+02:00",
        program_date="2024-07-22", period_start="2024-08-19", period_end="2024-08-23",
        shares=401_600, avg="7.94", amount="3188994",
        cumulative_shares=959_100, cumulative_avg="7.88", cumulative_amount="7555288",
        max_shares=4_554_986, treasury=4_647_464,
    ),
    _entry(
        release_date="2024-09-01", published_at="2024-09-01T19:54:00+02:00",
        program_date="2024-07-22", period_start="2024-08-26", period_end="2024-08-30",
        shares=438_600, avg="8.26", amount="3621488",
        cumulative_shares=1_397_700, cumulative_avg="8.00", cumulative_amount="11176776",
        max_shares=4_554_986, treasury=5_086_064,
    ),
    _entry(
        release_date="2024-09-07", published_at="2024-09-07T21:41:00+02:00",
        program_date="2024-07-22", period_start="2024-09-02", period_end="2024-09-06",
        shares=446_900, avg="8.37", amount="3738428",
        cumulative_shares=1_844_600, cumulative_avg="8.09", cumulative_amount="14915204",
        max_shares=4_554_986, treasury=5_532_964,
    ),
    _entry(
        release_date="2024-09-14", published_at="2024-09-14T08:13:00+02:00",
        program_date="2024-07-22", period_start="2024-09-09", period_end="2024-09-13",
        shares=282_900, avg="8.37", amount="2369283",
        cumulative_shares=2_127_500, cumulative_avg="8.12", cumulative_amount="17284487",
        max_shares=4_554_986, treasury=5_815_864,
    ),
    _entry(
        release_date="2024-09-21", published_at="2024-09-21T03:47:00+02:00",
        program_date="2024-07-22", period_start="2024-09-16", period_end="2024-09-20",
        shares=172_100, avg="8.32", amount="1432207",
        cumulative_shares=2_299_600, cumulative_avg="8.14", cumulative_amount="18716695",
        max_shares=4_554_986, treasury=5_987_964,
    ),
    _entry(
        release_date="2024-09-28", published_at="2024-09-28T02:35:00+02:00",
        program_date="2024-07-22", period_start="2024-09-23", period_end="2024-09-27",
        shares=118_300, avg="7.94", amount="939622",
        cumulative_shares=2_417_900, cumulative_avg="8.13", cumulative_amount="19656317",
        max_shares=4_554_986, treasury=6_106_264,
    ),
    _entry(
        release_date="2024-10-05", published_at="2024-10-05T21:55:00+02:00",
        program_date="2024-07-22", period_start="2024-09-30", period_end="2024-10-04",
        shares=120_900, avg="7.93", amount="958554",
        cumulative_shares=2_538_800, cumulative_avg="8.12", cumulative_amount="20614871",
        max_shares=4_554_986, treasury=6_227_164,
    ),
    _entry(
        release_date="2024-10-13", published_at="2024-10-13T20:11:00+02:00",
        program_date="2024-07-22", period_start="2024-10-07", period_end="2024-10-11",
        shares=102_000, avg="7.99", amount="815269",
        cumulative_shares=2_640_800, cumulative_avg="8.12", cumulative_amount="21430140",
        max_shares=4_554_986, treasury=6_329_164,
    ),
    _entry(
        release_date="2024-10-20", published_at="2024-10-20T19:56:00+02:00",
        program_date="2024-07-22", period_start="2024-10-14", period_end="2024-10-18",
        shares=80_832, avg="7.89", amount="638125",
        cumulative_shares=2_721_632, cumulative_avg="8.11", cumulative_amount="22068265",
        max_shares=4_554_986, treasury=6_409_996,
    ),
    _entry(
        release_date="2024-10-27", published_at="2024-10-27T20:55:00+01:00",
        program_date="2024-07-22", period_start="2024-10-21", period_end="2024-10-25",
        shares=64_200, avg="7.92", amount="508417",
        cumulative_shares=2_785_832, cumulative_avg="8.10", cumulative_amount="22576682",
        max_shares=4_554_986, treasury=6_474_196,
    ),
    _entry(
        release_date="2024-11-03", published_at="2024-11-03T21:21:00+01:00",
        program_date="2024-07-22", period_start="2024-10-28", period_end="2024-11-01",
        shares=50_000, avg="7.94", amount="397196",
        cumulative_shares=2_835_832, cumulative_avg="8.10", cumulative_amount="22973878",
        max_shares=4_554_986, treasury=6_524_196,
    ),
    _entry(
        release_date="2024-11-08", published_at="2024-11-08T21:35:00+01:00",
        program_date="2024-07-22", period_start="2024-11-04", period_end="2024-11-08",
        shares=45_300, avg="7.84", amount="355165",
        cumulative_shares=2_881_132, cumulative_avg="8.10", cumulative_amount="23329043",
        max_shares=4_554_986, treasury=6_569_496,
    ),
    _entry(
        release_date="2024-11-17", published_at="2024-11-17T19:59:00+01:00",
        program_date="2024-07-22", period_start="2024-11-11", period_end="2024-11-15",
        shares=24_101, avg="7.86", amount="189392",
        cumulative_shares=2_905_233, cumulative_avg="8.10", cumulative_amount="23518435",
        max_shares=4_554_986, treasury=6_593_597,
    ),
    _entry(
        release_date="2024-11-24", published_at="2024-11-24T19:10:00+01:00",
        program_date="2024-07-22", period_start="2024-11-18", period_end="2024-11-22",
        shares=39_450, avg="7.85", amount="309588",
        cumulative_shares=2_944_683, cumulative_avg="8.09", cumulative_amount="23828023",
        max_shares=4_554_986, treasury=6_633_047,
    ),
    _entry(
        release_date="2024-12-01", published_at="2024-12-01T19:18:00+01:00",
        program_date="2024-07-22", period_start="2024-11-25", period_end="2024-11-29",
        shares=56_800, avg="7.86", amount="446585",
        cumulative_shares=3_001_483, cumulative_avg="8.09", cumulative_amount="24274608",
        max_shares=4_554_986, treasury=6_689_847,
    ),
    _entry(
        release_date="2024-12-07", published_at="2024-12-07T20:57:00+01:00",
        program_date="2024-07-22", period_start="2024-12-02", period_end="2024-12-06",
        shares=117_900, avg="7.78", amount="917480",
        cumulative_shares=3_119_383, cumulative_avg="8.08", cumulative_amount="25192089",
        max_shares=4_554_986, treasury=6_807_747,
    ),
    _entry(
        release_date="2024-12-13", published_at="2024-12-13T21:45:00+01:00",
        program_date="2024-07-22", period_start="2024-12-09", period_end="2024-12-13",
        shares=216_900, avg="7.77", amount="1686361",
        cumulative_shares=3_336_283, cumulative_avg="8.06", cumulative_amount="26878449",
        max_shares=4_554_986, treasury=7_024_647,
    ),
    _entry(
        release_date="2024-12-22", published_at="2024-12-22T20:52:00+01:00",
        program_date="2024-07-22", period_start="2024-12-16", period_end="2024-12-20",
        shares=286_200, avg="7.63", amount="2184692",
        cumulative_shares=3_622_483, cumulative_avg="8.02", cumulative_amount="29063141",
        max_shares=4_554_986, treasury=7_310_847,
    ),
    _entry(
        release_date="2024-12-29", published_at="2024-12-29T14:29:00+01:00",
        program_date="2024-07-22", period_start="2024-12-23", period_end="2024-12-27",
        shares=117_180, avg="7.49", amount="877167",
        cumulative_shares=3_739_663, cumulative_avg="8.01", cumulative_amount="29940308",
        max_shares=4_554_986, treasury=7_428_027,
    ),
    _entry(
        release_date="2025-01-03", published_at="2025-01-03T20:33:00+01:00",
        program_date="2024-07-22", period_start="2024-12-30", period_end="2025-01-03",
        shares=193_800, avg="7.67", amount="1485870",
        cumulative_shares=3_933_463, cumulative_avg="7.99", cumulative_amount="31425994",
        max_shares=4_554_986, treasury=7_621_827,
    ),
    _entry(
        release_date="2025-01-11", published_at="2025-01-11T20:31:00+01:00",
        program_date="2024-07-22", period_start="2025-01-06", period_end="2025-01-10",
        shares=354_639, avg="7.79", amount="2764001",
        cumulative_shares=4_288_102, cumulative_avg="7.97", cumulative_amount="34189994",
        max_shares=4_554_986, treasury=7_976_466,
    ),
    _entry(
        release_date="2025-01-18", published_at="2025-01-18T09:19:00+01:00",
        program_date="2024-07-22", period_start="2025-01-13", period_end="2025-01-17",
        shares=266_794, avg="7.74", amount="2066309",
        cumulative_shares=4_554_896, cumulative_avg="7.96", cumulative_amount="36256303",
        max_shares=4_554_986, treasury=8_243_260,
    ),
]


# Continuation under the same 2024 AGM authorization, explicitly initiated 3 February
# 2025 for the remaining 866,690 shares. Euronext calls this a continuation but reports
# a fresh cumulative sequence, so it is intentionally modeled as a separate program.
FEBRUARY_2025_CONTINUATION = [
    _entry(
        release_date="2025-02-08", published_at="2025-02-08T17:00:00+01:00",
        program_date="2025-02-03", period_start="2025-02-03", period_end="2025-02-07",
        shares=303_000, avg="7.60", amount="2302790",
        cumulative_shares=303_000, cumulative_avg="7.60", cumulative_amount="2302790",
        max_shares=866_690, treasury=8_546_260,
    ),
    _entry(
        release_date="2025-02-14", published_at="2025-02-14T22:50:00+01:00",
        program_date="2025-02-03", period_start="2025-02-10", period_end="2025-02-14",
        shares=346_900, avg="7.58", amount="2631058",
        cumulative_shares=649_900, cumulative_avg="7.59", cumulative_amount="4933848",
        max_shares=866_690, treasury=8_893_160,
    ),
    _entry(
        release_date="2025-02-19", published_at="2025-02-19T22:27:00+01:00",
        program_date="2025-02-03", period_start="2025-02-17", period_end="2025-02-19",
        shares=216_790, avg="7.58", amount="1642700",
        cumulative_shares=866_690, cumulative_avg="7.59", cumulative_amount="6576548",
        max_shares=866_690, treasury=9_109_950,
    ),
]


OLDER_2024_OFFICIAL_BUYBACKS = JULY_2024_PROGRAM + FEBRUARY_2025_CONTINUATION

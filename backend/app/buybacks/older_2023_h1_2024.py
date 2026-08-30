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
    treasury: int | None = None,
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
            treasury_shares_after=cumulative_shares if treasury is None else treasury,
        ),
    }


# Continuation in 1H 2024 of the buyback program initiated 20 June 2023.
# These are structured transcriptions of the Euronext / Oslo Bors Newspoint status
# releases. Raw issuer values are preserved here; cumulative-control and known stale
# treasury disclosures are reconciled only in older_2023_reconciled.py.
H1_2024_CONTINUATION = [
    _entry(
        release_date="2024-01-07", period_start="2024-01-02", period_end="2024-01-05",
        shares=17_527, avg="8.01", amount="140460",
        cumulative_shares=3_197_554, cumulative_avg="8.58", cumulative_amount="27431359",
    ),
    _entry(
        release_date="2024-01-14", period_start="2024-01-08", period_end="2024-01-12",
        shares=31_504, avg="7.98", amount="251512",
        cumulative_shares=3_229_058, cumulative_avg="8.57", cumulative_amount="27682870",
    ),
    _entry(
        release_date="2024-01-21", period_start="2024-01-16", period_end="2024-01-19",
        shares=23_573, avg="7.93", amount="186891",
        cumulative_shares=3_252_631, cumulative_avg="8.57", cumulative_amount="27869761",
    ),
    _entry(
        release_date="2024-01-27", period_start="2024-01-22", period_end="2024-01-26",
        shares=9_192, avg="7.87", amount="72338",
        cumulative_shares=3_261_823, cumulative_avg="8.57", cumulative_amount="27942099",
    ),
    _entry(
        release_date="2024-02-03", period_start="2024-01-29", period_end="2024-02-01",
        shares=12_004, avg="8.06", amount="96735",
        cumulative_shares=3_273_827, cumulative_avg="8.56", cumulative_amount="28038834",
    ),
    _entry(
        release_date="2024-02-11", period_start="2024-02-07", period_end="2024-02-09",
        shares=4_665, avg="7.79", amount="36322",
        cumulative_shares=3_278_492, cumulative_avg="8.56", cumulative_amount="28075157",
        treasury=3_273_827,
        source_note=(
            "Issuer status reports cumulative program purchases of 3,278,492 shares, "
            "but repeats the preceding treasury balance of 3,273,827. The raw stale "
            "treasury figure is preserved here and reconciled in the model layer."
        ),
    ),
    _entry(
        release_date="2024-02-17", period_start="2024-02-12", period_end="2024-02-16",
        shares=5_041, avg="7.66", amount="38603",
        cumulative_shares=3_283_533, cumulative_avg="8.56", cumulative_amount="28113759",
    ),
    _entry(
        release_date="2024-02-24", period_start="2024-02-20", period_end="2024-02-23",
        shares=7_272, avg="7.75", amount="56358",
        cumulative_shares=3_290_805, cumulative_avg="8.56", cumulative_amount="28170118",
    ),
    _entry(
        release_date="2024-03-03", period_start="2024-02-26", period_end="2024-03-01",
        shares=10_007, avg="7.72", amount="77215",
        cumulative_shares=3_300_812, cumulative_avg="8.56", cumulative_amount="28247332",
    ),
    _entry(
        release_date="2024-03-08", period_start="2024-03-04", period_end="2024-03-08",
        shares=9_450, avg="7.74", amount="73178",
        cumulative_shares=3_310_262, cumulative_avg="8.56", cumulative_amount="28320510",
    ),
    _entry(
        release_date="2024-03-16", period_start="2024-03-12", period_end="2024-03-15",
        shares=12_421, avg="7.87", amount="97791",
        cumulative_shares=3_322_683, cumulative_avg="8.55", cumulative_amount="28418302",
    ),
    _entry(
        release_date="2024-03-22", period_start="2024-03-19", period_end="2024-03-22",
        shares=10_092, avg="7.80", amount="78735",
        cumulative_shares=3_332_775, cumulative_avg="8.55", cumulative_amount="28497037",
        treasury=3_322_683,
        source_note=(
            "Issuer status reports cumulative program purchases of 3,332,775 shares, "
            "but repeats the preceding treasury balance of 3,322,683. The raw stale "
            "treasury figure is preserved here and reconciled in the model layer."
        ),
    ),
    _entry(
        release_date="2024-03-27", period_start="2024-03-25", period_end="2024-03-27",
        shares=13_000, avg="8.18", amount="106285",
        cumulative_shares=3_345_775, cumulative_avg="8.55", cumulative_amount="28603322",
    ),
    _entry(
        release_date="2024-04-07", period_start="2024-04-02", period_end="2024-04-05",
        shares=24_315, avg="8.29", amount="201665",
        cumulative_shares=3_370_090, cumulative_avg="8.55", cumulative_amount="28804987",
    ),
    _entry(
        release_date="2024-04-14", period_start="2024-04-08", period_end="2024-04-12",
        shares=25_290, avg="8.14", amount="205916",
        cumulative_shares=3_395_380, cumulative_avg="8.54", cumulative_amount="29010903",
    ),
    _entry(
        release_date="2024-04-21", period_start="2024-04-15", period_end="2024-04-19",
        shares=36_299, avg="8.12", amount="294577",
        cumulative_shares=3_431_679, cumulative_avg="8.54", cumulative_amount="29305480",
    ),
    _entry(
        release_date="2024-04-28", period_start="2024-04-22", period_end="2024-04-26",
        shares=48_799, avg="8.05", amount="392667",
        cumulative_shares=3_480_478, cumulative_avg="8.53", cumulative_amount="29698147",
    ),
    _entry(
        release_date="2024-05-05", period_start="2024-04-29", period_end="2024-05-03",
        shares=34_755, avg="7.83", amount="272110",
        cumulative_shares=3_515_233, cumulative_avg="8.53", cumulative_amount="29970258",
    ),
    _entry(
        release_date="2024-05-12", period_start="2024-05-06", period_end="2024-05-10",
        shares=40_727, avg="7.75", amount="315739",
        cumulative_shares=3_555_960, cumulative_avg="8.52", cumulative_amount="30285996",
    ),
    _entry(
        release_date="2024-05-18", period_start="2024-05-13", period_end="2024-05-16",
        shares=45_610, avg="7.72", amount="352177",
        cumulative_shares=3_601_570, cumulative_avg="8.51", cumulative_amount="30638174",
    ),
    _entry(
        release_date="2024-05-24", period_start="2024-05-21", period_end="2024-05-23",
        shares=41_320, avg="7.69", amount="317868",
        cumulative_shares=3_642_890, cumulative_avg="8.50", cumulative_amount="30956041",
    ),
    _entry(
        release_date="2024-06-01", period_start="2024-05-27", period_end="2024-05-31",
        shares=45_474, avg="7.72", amount="350965",
        cumulative_shares=3_688_364, cumulative_avg="8.49", cumulative_amount="31307006",
    ),
]

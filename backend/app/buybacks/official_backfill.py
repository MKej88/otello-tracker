from __future__ import annotations

from decimal import Decimal

from app.buybacks.euronext import BuybackStatus, ingest_buyback_status


def _status(
    *,
    program_reference_date: str,
    period_start: str,
    period_end: str,
    period_shares: int,
    period_avg_price_nok: str,
    period_amount_nok: str,
    cumulative_program_shares: int,
    cumulative_program_avg_price_nok: str,
    cumulative_program_amount_nok: str,
    max_program_shares: int,
    treasury_shares_after: int,
) -> BuybackStatus:
    return BuybackStatus(
        program_reference_date=program_reference_date,
        period_start=period_start,
        period_end=period_end,
        period_shares=period_shares,
        period_avg_price_nok=Decimal(period_avg_price_nok),
        period_amount_nok=Decimal(period_amount_nok),
        cumulative_program_shares=cumulative_program_shares,
        cumulative_program_avg_price_nok=Decimal(cumulative_program_avg_price_nok),
        cumulative_program_amount_nok=Decimal(cumulative_program_amount_nok),
        max_program_shares=max_program_shares,
        treasury_shares_after=treasury_shares_after,
    )


# Structured transcriptions of original Euronext / Oslo Bors Newspoint releases.
# These facts close gaps that are missing from the current public mirror feed. Keeping
# them structured avoids embedding issuer prose while retaining the canonical source URL.
KNOWN_OFFICIAL_BUYBACKS = [
    # Buyback program initiated 22 September 2025.
    {
        "published_at": "2025-09-29T04:39:00+02:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-09-29-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-09-22",
            period_end="2025-09-26",
            period_shares=159_500,
            period_avg_price_nok="14.25",
            period_amount_nok="2273640",
            cumulative_program_shares=159_500,
            cumulative_program_avg_price_nok="14.25",
            cumulative_program_amount_nok="2273640",
            max_program_shares=3_689_541,
            treasury_shares_after=159_500,
        ),
    },
    {
        "published_at": "2025-10-04T22:07:00+02:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-10-04-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-09-29",
            period_end="2025-10-03",
            period_shares=88_400,
            period_avg_price_nok="15.00",
            period_amount_nok="1326000",
            cumulative_program_shares=247_900,
            cumulative_program_avg_price_nok="14.52",
            cumulative_program_amount_nok="3599640",
            max_program_shares=3_689_541,
            treasury_shares_after=247_900,
        ),
    },
    {
        "published_at": "2025-10-12T10:29:00+02:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-10-12-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-10-06",
            period_end="2025-10-10",
            period_shares=252_131,
            period_avg_price_nok="14.92",
            period_amount_nok="3761506",
            cumulative_program_shares=500_031,
            cumulative_program_avg_price_nok="14.72",
            cumulative_program_amount_nok="7361146",
            max_program_shares=3_689_541,
            treasury_shares_after=500_031,
        ),
    },
    {
        "published_at": "2025-10-17T22:00:00+02:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-10-17-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-10-13",
            period_end="2025-10-17",
            period_shares=286_636,
            period_avg_price_nok="14.94",
            period_amount_nok="4282278",
            cumulative_program_shares=786_667,
            cumulative_program_avg_price_nok="14.80",
            cumulative_program_amount_nok="11643424",
            max_program_shares=3_689_541,
            treasury_shares_after=786_667,
        ),
    },
    {
        "published_at": "2025-10-24T23:19:00+02:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-10-24-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-10-20",
            period_end="2025-10-24",
            period_shares=227_975,
            period_avg_price_nok="14.96",
            period_amount_nok="3410518",
            cumulative_program_shares=1_014_642,
            cumulative_program_avg_price_nok="14.84",
            cumulative_program_amount_nok="15053942",
            max_program_shares=3_689_541,
            treasury_shares_after=1_014_642,
        ),
    },
    {
        "published_at": "2025-10-31T21:51:00+01:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-10-31-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-10-27",
            period_end="2025-10-31",
            period_shares=25_000,
            period_avg_price_nok="15.00",
            period_amount_nok="375000",
            cumulative_program_shares=1_039_642,
            cumulative_program_avg_price_nok="14.84",
            cumulative_program_amount_nok="15428942",
            max_program_shares=3_689_541,
            treasury_shares_after=1_039_642,
        ),
    },
    {
        "published_at": "2025-11-07T23:02:00+01:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-11-07-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-11-03",
            period_end="2025-11-07",
            period_shares=0,
            period_avg_price_nok="0",
            period_amount_nok="0",
            cumulative_program_shares=1_039_642,
            cumulative_program_avg_price_nok="14.84",
            cumulative_program_amount_nok="15428942",
            max_program_shares=3_689_541,
            treasury_shares_after=1_039_642,
        ),
    },
    {
        "published_at": "2025-11-14T22:03:00+01:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-11-14-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-11-10",
            period_end="2025-11-14",
            period_shares=0,
            period_avg_price_nok="0",
            period_amount_nok="0",
            cumulative_program_shares=1_039_642,
            cumulative_program_avg_price_nok="14.84",
            cumulative_program_amount_nok="15428942",
            max_program_shares=3_689_541,
            treasury_shares_after=1_039_642,
        ),
    },
    {
        "published_at": "2025-11-21T22:35:00+01:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-11-21-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-11-17",
            period_end="2025-11-21",
            period_shares=109_000,
            period_avg_price_nok="16.67",
            period_amount_nok="1831883",
            cumulative_program_shares=1_149_542,
            cumulative_program_avg_price_nok="15.02",
            cumulative_program_amount_nok="17260826",
            max_program_shares=3_689_541,
            treasury_shares_after=1_149_542,
        ),
    },
    {
        "published_at": "2025-11-30T19:42:00+01:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-11-30-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-11-24",
            period_end="2025-11-28",
            period_shares=162_700,
            period_avg_price_nok="18.03",
            period_amount_nok="2934205",
            cumulative_program_shares=1_312_242,
            cumulative_program_avg_price_nok="15.39",
            cumulative_program_amount_nok="20195031",
            max_program_shares=3_689_541,
            treasury_shares_after=1_312_242,
        ),
    },
    {
        "published_at": "2025-12-05T21:23:00+01:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2025-12-05-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2025-09-22",
            period_start="2025-12-01",
            period_end="2025-12-05",
            period_shares=203_900,
            period_avg_price_nok="18.65",
            period_amount_nok="3802025",
            cumulative_program_shares=1_516_142,
            cumulative_program_avg_price_nok="15.83",
            cumulative_program_amount_nok="23997056",
            max_program_shares=3_689_541,
            treasury_shares_after=1_516_142,
        ),
    },
    # Public mirror feed omission in the February 2026 program.
    {
        "published_at": "2026-04-25T21:36:00+02:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2026-04-25-otello-corporation-share-buyback-program-status",
        "status": _status(
            program_reference_date="2026-02-09",
            period_start="2026-04-20",
            period_end="2026-04-24",
            period_shares=103_200,
            period_avg_price_nok="19.81",
            period_amount_nok="2044239",
            cumulative_program_shares=1_077_616,
            cumulative_program_avg_price_nok="18.23",
            cumulative_program_amount_nok="19650064",
            max_program_shares=3_689_541,
            treasury_shares_after=4_767_157,
        ),
    },
]


def seed_known_official_buybacks(database_path: str | None = None) -> list[dict]:
    results: list[dict] = []
    for item in KNOWN_OFFICIAL_BUYBACKS:
        result = ingest_buyback_status(
            parsed=item["status"],
            url=item["url"],
            published_at=item["published_at"],
            database_path=database_path,
            source_code="EURONEXT",
            source_metadata={
                "source_quality": "CURATED_OFFICIAL",
                "provider": "Oslo Bors Newspoint",
                "structured_transcription": True,
                "reason": "Structured backfill from the original Euronext / Oslo Bors release where the current mirror feed is incomplete.",
            },
        )
        results.append(result)
    return results

from __future__ import annotations

from decimal import Decimal

from app.buybacks.euronext import BuybackStatus, ingest_buyback_status

EURONEXT_NEWS = "https://live.euronext.com/en/products/equities/company-news"

# These issuer status weeks explicitly reported no purchases. They are retained as
# audit facts, but are not inserted into `buybacks`, whose schema represents purchases
# and therefore requires shares > 0. The unchanged cumulative totals bridge cleanly
# across these dates in the coverage validator.
ZERO_PURCHASE_WEEKS = (
    ("2025-11-03", "2025-11-07", 1_039_642, Decimal("15428942")),
    ("2025-11-10", "2025-11-14", 1_039_642, Decimal("15428942")),
)


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


# Structured transcriptions of original Euronext / Oslo Bors Newspoint releases.
# They close gaps in the currently exposed mirror feed while avoiding verbatim issuer
# prose. Every row retains its canonical Euronext URL and exact published figures.
KNOWN_OFFICIAL_BUYBACKS = [
    _entry(
        release_date="2025-09-29", published_at="2025-09-29T04:39:00+02:00",
        program_date="2025-09-22", period_start="2025-09-22", period_end="2025-09-26",
        shares=159_500, avg="14.25", amount="2273640",
        cumulative_shares=159_500, cumulative_avg="14.25", cumulative_amount="2273640",
        max_shares=3_689_541, treasury=159_500,
    ),
    _entry(
        release_date="2025-10-04", published_at="2025-10-04T22:07:00+02:00",
        program_date="2025-09-22", period_start="2025-09-29", period_end="2025-10-03",
        shares=88_400, avg="15.00", amount="1326000",
        cumulative_shares=247_900, cumulative_avg="14.52", cumulative_amount="3599640",
        max_shares=3_689_541, treasury=247_900,
    ),
    _entry(
        release_date="2025-10-12", published_at="2025-10-12T10:29:00+02:00",
        program_date="2025-09-22", period_start="2025-10-06", period_end="2025-10-10",
        shares=252_131, avg="14.92", amount="3761506",
        cumulative_shares=500_031, cumulative_avg="14.72", cumulative_amount="7361146",
        max_shares=3_689_541, treasury=500_031,
    ),
    _entry(
        release_date="2025-10-17", published_at="2025-10-17T22:00:00+02:00",
        program_date="2025-09-22", period_start="2025-10-13", period_end="2025-10-17",
        shares=286_636, avg="14.94", amount="4282278",
        cumulative_shares=786_667, cumulative_avg="14.80", cumulative_amount="11643424",
        max_shares=3_689_541, treasury=786_667,
    ),
    _entry(
        release_date="2025-10-24", published_at="2025-10-24T23:19:00+02:00",
        program_date="2025-09-22", period_start="2025-10-20", period_end="2025-10-24",
        shares=227_975, avg="14.96", amount="3410518",
        cumulative_shares=1_014_642, cumulative_avg="14.84", cumulative_amount="15053942",
        max_shares=3_689_541, treasury=1_014_642,
    ),
    _entry(
        release_date="2025-10-31", published_at="2025-10-31T21:51:00+01:00",
        program_date="2025-09-22", period_start="2025-10-27", period_end="2025-10-31",
        shares=25_000, avg="15.00", amount="375000",
        cumulative_shares=1_039_642, cumulative_avg="14.84", cumulative_amount="15428942",
        max_shares=3_689_541, treasury=1_039_642,
    ),
    _entry(
        release_date="2025-11-21", published_at="2025-11-21T22:35:00+01:00",
        program_date="2025-09-22", period_start="2025-11-17", period_end="2025-11-21",
        shares=109_900, avg="16.67", amount="1831883",
        cumulative_shares=1_149_542, cumulative_avg="15.02", cumulative_amount="17260826",
        max_shares=3_689_541, treasury=1_149_542,
        source_note=(
            "Issuer release prose states 109,000 weekly shares, but that conflicts with "
            "the cumulative increase (1,149,542 - 1,039,642 = 109,900) and with the "
            "published NOK 1,831,883 consideration / NOK 16.67 average. Stored 109,900 "
            "as the internally reconciled figure; discrepancy is preserved in metadata."
        ),
    ),
    _entry(
        release_date="2025-11-30", published_at="2025-11-30T19:42:00+01:00",
        program_date="2025-09-22", period_start="2025-11-24", period_end="2025-11-28",
        shares=162_700, avg="18.03", amount="2934205",
        cumulative_shares=1_312_242, cumulative_avg="15.39", cumulative_amount="20195031",
        max_shares=3_689_541, treasury=1_312_242,
    ),
    _entry(
        release_date="2025-12-05", published_at="2025-12-05T21:23:00+01:00",
        program_date="2025-09-22", period_start="2025-12-01", period_end="2025-12-05",
        shares=203_900, avg="18.65", amount="3802025",
        cumulative_shares=1_516_142, cumulative_avg="15.83", cumulative_amount="23997056",
        max_shares=3_689_541, treasury=1_516_142,
    ),
    # One release omitted by the public mirror in the February 2026 program.
    _entry(
        release_date="2026-04-25", published_at="2026-04-25T21:36:00+02:00",
        program_date="2026-02-09", period_start="2026-04-20", period_end="2026-04-24",
        shares=103_200, avg="19.81", amount="2044239",
        cumulative_shares=1_077_616, cumulative_avg="18.23", cumulative_amount="19650064",
        max_shares=3_689_541, treasury=4_767_157,
    ),
]


def seed_known_official_buybacks(database_path: str | None = None) -> list[dict]:
    results: list[dict] = []
    for item in KNOWN_OFFICIAL_BUYBACKS:
        metadata = {
            "source_quality": "CURATED_OFFICIAL",
            "provider": "Oslo Bors Newspoint",
            "structured_transcription": True,
            "reason": "Structured backfill from original Euronext / Oslo Bors releases where the current mirror feed is incomplete.",
        }
        if item["source_note"]:
            metadata.update(
                {
                    "issuer_text_discrepancy": True,
                    "discrepancy_note": item["source_note"],
                }
            )
        results.append(
            ingest_buyback_status(
                parsed=item["status"],
                url=item["url"],
                published_at=item["published_at"],
                database_path=database_path,
                source_code="EURONEXT",
                source_metadata=metadata,
            )
        )
    return results

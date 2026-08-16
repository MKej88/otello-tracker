from __future__ import annotations

from decimal import Decimal

from app.buybacks.euronext import BuybackStatus, ingest_buyback_status

# The public mirror feed omits this one weekly release. The figures below are a
# structured transcription of the original Euronext/Oslo Bors Newspoint release.
# Keeping the fact record structured avoids embedding the issuer's release prose.
KNOWN_OFFICIAL_BUYBACKS = [
    {
        "published_at": "2026-04-25T21:36:00+02:00",
        "url": "https://live.euronext.com/en/products/equities/company-news/2026-04-25-otello-corporation-share-buyback-program-status",
        "status": BuybackStatus(
            program_reference_date="2026-02-09",
            period_start="2026-04-20",
            period_end="2026-04-24",
            period_shares=103_200,
            period_avg_price_nok=Decimal("19.81"),
            period_amount_nok=Decimal("2044239"),
            cumulative_program_shares=1_077_616,
            cumulative_program_avg_price_nok=Decimal("18.23"),
            cumulative_program_amount_nok=Decimal("19650064"),
            max_program_shares=3_689_541,
            treasury_shares_after=4_767_157,
        ),
    }
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
                "reason": "Public MFN mirror feed omits this weekly release; seeded from original Euronext release.",
            },
        )
        results.append(result)
    return results

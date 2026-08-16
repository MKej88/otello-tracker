from decimal import Decimal

from app.buybacks.coverage import buyback_coverage_gaps
from app.buybacks.euronext import BuybackStatus, ingest_buyback_status
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def _status(*, end: str, shares: int, amount: str, cumulative_shares: int, cumulative_amount: str, treasury: int) -> BuybackStatus:
    return BuybackStatus(
        program_reference_date="2026-02-09",
        period_start=end,
        period_end=end,
        period_shares=shares,
        period_avg_price_nok=Decimal(amount) / Decimal(shares),
        period_amount_nok=Decimal(amount),
        cumulative_program_shares=cumulative_shares,
        cumulative_program_avg_price_nok=Decimal(cumulative_amount) / Decimal(cumulative_shares),
        cumulative_program_amount_nok=Decimal(cumulative_amount),
        max_program_shares=3_689_541,
        treasury_shares_after=treasury,
    )


def test_cumulative_values_expose_missing_week(tmp_path) -> None:
    database = str(tmp_path / "coverage.db")
    init_database(database)
    seed_curated_history(database)

    ingest_buyback_status(
        parsed=_status(
            end="2026-04-17", shares=100, amount="1000",
            cumulative_shares=100, cumulative_amount="1000", treasury=100,
        ),
        url="https://example.invalid/week-1",
        published_at="2026-04-17T20:00:00Z",
        database_path=database,
        source_code="EURONEXT",
    )
    ingest_buyback_status(
        parsed=_status(
            end="2026-04-30", shares=50, amount="500",
            cumulative_shares=175, cumulative_amount="1750", treasury=175,
        ),
        url="https://example.invalid/week-3",
        published_at="2026-04-30T20:00:00Z",
        database_path=database,
        source_code="EURONEXT",
    )

    gaps = buyback_coverage_gaps(database)
    assert len(gaps) == 1
    assert gaps[0]["missing_shares"] == 25
    assert gaps[0]["missing_amount_nok"] == "250"
    assert gaps[0]["after_date"] == "2026-04-17"
    assert gaps[0]["before_date"] == "2026-04-30"

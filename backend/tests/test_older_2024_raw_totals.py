from decimal import Decimal

from app.buybacks.older_2024 import FEBRUARY_2025_CONTINUATION, JULY_2024_PROGRAM


def test_raw_2024_program_matches_published_final_cumulative_totals() -> None:
    assert len(JULY_2024_PROGRAM) == 26
    assert sum(row["status"].period_shares for row in JULY_2024_PROGRAM) == 4_554_896
    assert JULY_2024_PROGRAM[-1]["status"].cumulative_program_shares == 4_554_896
    assert JULY_2024_PROGRAM[-1]["status"].cumulative_program_amount_nok == Decimal("36256303")
    # Raw issuer weekly values intentionally do not sum to the final cumulative value;
    # the discrepancy is preserved in the raw dataset and reconciled separately.
    assert sum(row["status"].period_amount_nok for row in JULY_2024_PROGRAM) == Decimal("36256488")


def test_raw_february_continuation_matches_published_totals() -> None:
    assert len(FEBRUARY_2025_CONTINUATION) == 3
    assert sum(row["status"].period_shares for row in FEBRUARY_2025_CONTINUATION) == 866_690
    assert sum(row["status"].period_amount_nok for row in FEBRUARY_2025_CONTINUATION) == Decimal("6576548")
    assert FEBRUARY_2025_CONTINUATION[-1]["status"].cumulative_program_shares == 866_690
    assert FEBRUARY_2025_CONTINUATION[-1]["status"].cumulative_program_amount_nok == Decimal("6576548")

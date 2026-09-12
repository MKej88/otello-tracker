from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEDULED = ROOT / "cloudflare" / "src" / "scheduled.py"


def test_fast_refresh_materializes_confirmed_bemobi_cash_before_nav() -> None:
    source = SCHEDULED.read_text(encoding="utf-8")

    sync_position = source.index('"bemobi_distribution_cash"')
    nav_position = source.index('"dirty_nav"', sync_position)

    assert sync_position < nav_position
    assert (
        "sync_confirmed_bemobi_distribution_cash(\n            repository,\n            target_date=newsweb_date,"
        in source
    )
    assert 'await renew("after Bemobi distribution cash")' in source


def test_fast_refresh_counts_bemobi_cash_changes_and_surfaces_partial_sync() -> None:
    source = SCHEDULED.read_text(encoding="utf-8")

    assert '("bemobi_distribution_cash", "rows_written")' in source
    assert '("bemobi_distribution_cash", "rows_updated")' in source
    assert '"error_type": "BemobiDistributionCashPartial"' in source
    assert '"automatic_bemobi_distribution_cash": True' in source


def test_fast_refresh_imports_distribution_sync_in_worker_and_local_modes() -> None:
    source = SCHEDULED.read_text(encoding="utf-8")

    assert (
        "from .bemobi_distribution_sync import sync_confirmed_bemobi_distribution_cash"
        in source
    )
    assert (
        "from bemobi_distribution_sync import sync_confirmed_bemobi_distribution_cash"
        in source
    )

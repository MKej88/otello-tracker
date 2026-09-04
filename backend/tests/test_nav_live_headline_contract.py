from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NAV_PAGE = ROOT / "frontend" / "src" / "NavPageV2.tsx"


def test_nav_headline_prefers_live_economic_nav_over_materialized_period() -> None:
    page = NAV_PAGE.read_text(encoding="utf-8")

    assert 'const { data: live } = usePollingResource<EstimatedNav>("/api/dashboard/economic", REFRESH_MS);' in page
    assert 'const displayedNavPerShare = live?.ready && live.nav_per_share != null' in page
    assert '? live.nav_per_share\n    : current?.nav_per_share;' in page
    assert 'const displayedSharesOutstanding = live?.ready && live.shares_outstanding != null' in page
    assert '? live.shares_outstanding\n    : current?.shares_outstanding;' in page
    assert 'const displayedDiscountPct = live?.ready && live.discount_pct != null' in page
    assert '? live.discount_pct\n    : current?.discount_pct;' in page

    assert 'const displayedNavPerShare = current?.nav_per_share ??' not in page
    assert 'const displayedSharesOutstanding = current?.shares_outstanding ??' not in page
    assert 'const displayedDiscountPct = current?.discount_pct ??' not in page

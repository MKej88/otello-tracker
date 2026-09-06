from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NAV_PAGE = ROOT / "frontend" / "src" / "NavPageV2.tsx"
WORKER_ECONOMIC = ROOT / "cloudflare" / "src" / "economic_nav_investor.py"
REFERENCE_ECONOMIC = ROOT / "backend" / "app" / "economic_nav_investor.py"
WORKER_COMPOSITION = ROOT / "cloudflare" / "src" / "live_nav_composition.py"
REFERENCE_COMPOSITION = ROOT / "backend" / "app" / "live_nav_composition.py"
HOT_SNAPSHOT = ROOT / "cloudflare" / "src" / "dashboard_hot_snapshot.py"


def test_nav_composition_prefers_same_live_payload_as_headline() -> None:
    page = NAV_PAGE.read_text(encoding="utf-8")

    assert "const liveCompositionReady = live?.ready === true" in page
    assert "&& live.composition_ready === true" in page
    assert "? (live?.composition ?? [])" in page
    assert "const compositionNavTotalMnok = liveCompositionReady" in page
    assert "const compositionNavPerShare = liveCompositionReady" in page
    assert "const compositionDate = liveCompositionReady" in page
    assert "dateLabel(compositionDate)" in page
    assert "value(compositionNavTotalMnok, 1)" in page
    assert "value(compositionNavPerShare)" in page


def test_period_attribution_remains_materialized_and_independent_of_live_composition() -> None:
    page = NAV_PAGE.read_text(encoding="utf-8")

    assert "const change = data?.change;" in page
    assert "fetchPreloadedJson<Payload>(discountHistoryUrl(period))" in page
    assert "dateLabel(change.current_date)" in page
    assert "live?.change" not in page


def test_economic_payload_exposes_reconciled_live_composition_in_both_runtimes() -> None:
    for path in (WORKER_ECONOMIC, REFERENCE_ECONOMIC):
        source = path.read_text(encoding="utf-8")
        assert "live_nav_composition" in source
        assert '"nav_total_mnok"' in source
        assert '"composition_ready"' in source
        assert '"composition_date"' in source
        assert '"composition"' in source
        assert '"live_composition_nav_mismatch"' in source


def test_live_composition_reuses_one_day_history_math_not_period_attribution() -> None:
    source = WORKER_COMPOSITION.read_text(encoding="utf-8")

    assert "_estimated_point(repository, day)" in source
    assert "_split_current_composition(repository, point, life360_state)" in source
    assert "discount_history" not in source
    assert "_change(" not in source


def test_live_composition_preserves_explicit_bemobi_cash_display() -> None:
    for path in (WORKER_COMPOSITION, REFERENCE_COMPOSITION):
        source = path.read_text(encoding="utf-8")
        assert "_cash_breakdown" in source
        assert "_apply_bemobi_paid_split" in source
        assert "_apply_bemobi_receivable_split" in source
        assert "_receivable_state" in source
        assert "other_net_assets_daily_estimates" in source
        assert "_apply_current_bemobi_cash_display" in source


def test_hot_snapshot_version_is_bumped_for_new_economic_response_shape() -> None:
    source = HOT_SNAPSHOT.read_text(encoding="utf-8")

    assert 'STATE_KEY = "dashboard_hot_snapshot_v7"' in source
    assert "SNAPSHOT_VERSION = 7" in source

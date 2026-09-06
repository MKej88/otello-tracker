from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "frontend" / "src" / "OverviewPage.tsx"
OVERVIEW_EVENTS = ROOT / "cloudflare" / "src" / "overview_events.py"
BRAZIL_CACHE = ROOT / "cloudflare" / "src" / "brazil_focus_resilience.py"


def test_overview_uses_lightweight_company_and_macro_event_feed() -> None:
    overview = OVERVIEW.read_text(encoding="utf-8")
    event_feed = OVERVIEW_EVENTS.read_text(encoding="utf-8")
    brazil_cache = BRAZIL_CACHE.read_text(encoding="utf-8")

    assert '"/api/overview/events"' in overview
    assert '"/api/news-events"' not in overview
    assert '"/api/brazil/dashboard"' not in overview
    assert '"/api/bemobi/dashboard"' not in overview
    assert "bemobi_investor_facts" in event_feed
    assert "calendar_events(as_of_date=today_iso, focus={})" in event_feed
    assert "apply_cached_event_expectations" in event_feed
    assert "live_external_fetches" in event_feed
    assert "EVENT_STATE_KEY" in brazil_cache
    assert 'event.importance.startsWith("Høy")' in overview

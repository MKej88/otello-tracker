from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "frontend" / "src" / "OverviewPage.tsx"
NEWS_EVENTS = ROOT / "cloudflare" / "src" / "news_events.py"
BRAZIL = ROOT / "cloudflare" / "src" / "brazil_dashboard_v2.py"


def test_overview_uses_central_company_events_and_sourced_macro_calendar() -> None:
    overview = OVERVIEW.read_text(encoding="utf-8")
    news_events = NEWS_EVENTS.read_text(encoding="utf-8")
    brazil = BRAZIL.read_text(encoding="utf-8")

    assert '"/api/news-events"' in overview
    assert '"/api/brazil/dashboard"' in overview
    assert '"/api/bemobi/dashboard"' not in overview
    assert "bemobi_investor_facts" in news_events
    assert 'fact_type=\'NEXT_QUARTER\'' in news_events
    assert 'result["calendar"] = _annotate_market_consensus(enriched)' in brazil
    assert 'event.importance.startsWith("Høy")' in overview

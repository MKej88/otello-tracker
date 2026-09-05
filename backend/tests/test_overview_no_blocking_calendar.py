from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "frontend" / "src" / "OverviewPage.tsx"


def test_case_calendar_is_independent_of_live_nav_rendering() -> None:
    page = OVERVIEW.read_text(encoding="utf-8")

    assert 'const { data: nav } = usePollingResource<EstimatedNav>(' in page
    assert 'const { data: newsEvents } = usePollingResource<NewsEventsPayload>(' in page
    assert 'const { data: brazilCalendar } = usePollingResource<BrazilCalendarPayload>(' in page
    assert 'nav?.ready ? `${formatNumber(nav.nav_per_share, 2)} kr` : "Laster …"' in page
    assert 'const events = upcomingEvents(newsEvents, brazilCalendar);' in page

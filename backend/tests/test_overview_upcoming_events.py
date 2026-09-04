from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "frontend" / "src" / "OverviewPage.tsx"
CSS = ROOT / "frontend" / "src" / "investor-v2.css"


def test_overview_splits_nav_hero_and_shows_case_calendar() -> None:
    page = OVERVIEW.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert 'className="overviewHeroGrid"' in page
    assert 'className="card overviewNavCard"' in page
    assert 'className="card overviewUpcomingCard"' in page
    assert "NESTE VIKTIGE DATOER" in page
    assert "Hva bør følges nå?" in page
    assert '"/api/bemobi/dashboard"' in page
    assert '"/api/brazil/dashboard"' in page
    assert 'event.importance !== "Høy"' in page
    assert "buildUpcomingEvents" in page
    assert ".slice(0, 4)" in page
    assert "overviewHeroGrid" in css
    assert "grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr)" in css


def test_overview_next_event_uses_oslo_day_and_countdown() -> None:
    page = OVERVIEW.read_text(encoding="utf-8")

    assert 'timeZone: "Europe/Oslo"' in page
    assert 'if (days === 0) return "I dag";' in page
    assert 'if (days === 1) return "I morgen";' in page
    assert 'return days > 1 ? `Om ${days} dager` : "";' in page
    assert 'badge: "RESULTAT"' in page
    assert 'badge: "HØY"' in page

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "frontend" / "src" / "OverviewPage.tsx"
BEMOBI = ROOT / "cloudflare" / "src" / "bemobi_dashboard_base.py"
BRAZIL = ROOT / "cloudflare" / "src" / "brazil_dashboard_v2.py"


def test_overview_uses_existing_sourced_case_calendars() -> None:
    overview = OVERVIEW.read_text(encoding="utf-8")
    bemobi = BEMOBI.read_text(encoding="utf-8")
    brazil = BRAZIL.read_text(encoding="utf-8")

    assert '"/api/bemobi/dashboard"' in overview
    assert '"/api/brazil/dashboard"' in overview
    assert '"next_report": {' in bemobi
    assert '"date": next_quarter.get("report_date")' in bemobi
    assert 'result["calendar"] = _annotate_market_consensus(enriched)' in brazil
    assert 'event.importance !== "Høy"' in overview

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_overview_renders_all_freshness_rows_and_readable_sources() -> None:
    page = (FRONTEND / "OverviewPage.tsx").read_text(encoding="utf-8")

    for label in ("OTEC", "Bemobi", "Life360", "BRL/NOK", "NAV"):
        assert f'"{label}"' in page
    for source in ("Euronext", "B3", "Yahoo Finance", "Norges Bank", "Beregnet"):
        assert f'"{source}"' in page
    assert "Datakilder og ferskhet" in page
    assert "Rabatt til NAV" not in page
    assert "Kontrolleres hvert 30. minutt" not in page
    assert "MarketQuotePanelWithData" in page


def test_timestamp_formatter_is_null_safe_and_uses_date_for_older_data() -> None:
    helper = (FRONTEND / "dataFreshness.ts").read_text(encoding="utf-8")

    assert 'if (!parsed) return "—"' in helper
    assert "if (sameDay) return time" in helper
    assert "return `${date} · ${time}`" in helper
    assert "Number.isFinite(parsed.getTime())" in helper
    assert "NaN" not in helper
    assert "undefined" not in helper


def test_freshness_has_distinct_intraday_daily_and_missing_rules() -> None:
    helper = (FRONTEND / "dataFreshness.ts").read_text(encoding="utf-8")

    assert 'if (!observed) return "unavailable"' in helper
    assert 'if (cadence === "daily")' in helper
    assert 'if (businessAge <= 1) return "fresh"' in helper
    assert 'if (ageMinutes <= 60) return "fresh"' in helper
    assert 'if (ageMinutes <= 6 * 60) return "delayed"' in helper
    assert 'return "stale"' in helper

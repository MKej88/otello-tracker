from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_overview_uses_compact_market_strip_without_freshness_diagnostics() -> None:
    page = (FRONTEND / "OverviewPage.tsx").read_text(encoding="utf-8")

    for label in ("OTEC", "BMOB3", "BRL/NOK", "LIF", "MARKED"):
        assert label in page
    assert '"/api/market/quotes"' in page
    assert "overviewTickerGrid" in page
    assert "Datakilder og ferskhet" not in page
    assert "FreshnessCard" not in page
    assert "MarketQuotePanelWithData" not in page


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

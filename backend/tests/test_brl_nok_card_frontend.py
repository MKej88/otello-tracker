from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_brl_driver_renders_core_investor_fields_and_safe_fallbacks() -> None:
    page = (ROOT / "frontend/src/OverviewPage.tsx").read_text(encoding="utf-8")

    for text in (
        "daily_pct",
        "% siste måned",
        "kr NAV/aksje",
        "Dagens kurs",
    ):
        assert text in page
    assert "Sterkere BRL = positivt for Otello NAV" not in page
    assert 'return "—"' in page
    assert "Number.isFinite" in page
    assert "brl?.nav_effect_1m_per_share_nok" in page
    assert "summary?.brl_nok" in page
    assert "InsightRange" not in page

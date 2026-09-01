from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_brl_card_renders_investor_fields_and_safe_fallbacks() -> None:
    page = (ROOT / "frontend/src/OverviewPage.tsx").read_text(encoding="utf-8")

    for text in (
        "daily_pct",
        "1 mnd",
        "Siden ${brl.quarter_label}",
        "NAV-effekt 1 mnd",
        "range_1y",
        "Sterkere BRL = positivt for Otello NAV",
    ):
        assert text in page
    assert 'return "—"' in page
    assert "Number.isFinite" in page
    assert "InsightRange" in page
    assert "Math.max(0, Math.min(100, position))" in page

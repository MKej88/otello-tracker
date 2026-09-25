from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend/src/BuybackPage.tsx"


def test_buyback_page_prioritizes_shareholder_value_creation() -> None:
    source = PAGE.read_text(encoding="utf-8")

    for label in (
        "Verdiskaping fra tilbakekjøp",
        "Netto NAV-effekt",
        "Kapital brukt",
        "Gjennomsnittlig kjøpskurs",
        "Aksjer kjøpt tilbake",
        "Effekt av færre aksjer",
        "Netto verdi skapt",
        "Programstatus",
        "Hvordan programmet faktisk gjennomføres",
    ):
        assert label in source

    for removed_label in (
        "Bemobi per 1 000 OTEC",
        "Slik leses effekten",
    ):
        assert removed_label not in source

    assert "share_count_nav_effect_per_share_nok" in source


def test_buyback_page_does_not_request_unused_bemobi_data() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "/api/bemobi/dashboard" not in source
    assert "BemobiDashboard" not in source

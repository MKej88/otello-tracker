from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "frontend" / "src" / "OverviewPage.tsx"
BRAZIL = ROOT / "frontend" / "src" / "BrazilPage.tsx"


def test_overview_uses_the_same_norwegian_macro_terms_as_brazil_page() -> None:
    overview = OVERVIEW.read_text(encoding="utf-8")
    brazil = BRAZIL.read_text(encoding="utf-8")

    shared_labels = (
        "Rentebeslutning fra sentralbanken",
        "Foreløpig prisvekst",
        "Prisvekst",
        "Økonomisk vekst (BNP)",
        "Aktivitet i tjenestenæringene",
        "Omsetning i detaljhandelen",
        "Samlet økonomisk aktivitet",
        "Arbeidsledighet",
    )
    for label in shared_labels:
        assert label in brazil
        assert label in overview

    assert 'return "BCB – rentebeslutning"' not in overview
    assert '"Brasil – IPCA-15"' not in overview
    assert '"Brasil – IPCA"' not in overview
    assert 'event.importance.startsWith("Høy")' in overview

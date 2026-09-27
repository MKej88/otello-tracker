import re
from pathlib import Path


FRONTEND = Path(__file__).parents[2] / "frontend" / "src"
MAIN_PAGE_FILES = (
    "OverviewPage.tsx",
    "NavPageV2.tsx",
    "NavSensitivityPage.tsx",
    "EstimatedHistoryPage.tsx",
    "BuybackPage.tsx",
    "CashPage.tsx",
    "BemobiPageBase.tsx",
    "FxPage.tsx",
    "BrazilPage.tsx",
    "ConsensusPage.tsx",
    "NewsEventsPage.tsx",
    "DataQualityPage.tsx",
)


def source(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_investor_app_owns_the_only_page_h1() -> None:
    app = source("InvestorApp.tsx")

    assert len(re.findall(r"<h1(?:\s|>)", app)) == 1
    assert "<h1>{viewTitles[view]}</h1>" in app
    for page_file in MAIN_PAGE_FILES:
        assert not re.search(r"<h1(?:\s|>)", source(page_file)), page_file


def test_main_pages_use_only_h2_and_h3_below_the_page_title() -> None:
    for page_file in MAIN_PAGE_FILES:
        page = source(page_file)
        assert not re.search(r"<h[4-6](?:\s|>)", page), page_file


def test_section_labels_are_followed_by_semantic_headings() -> None:
    expected_headings = {
        "BemobiPageBase.tsx": (
            '<h3>Multipelsensitivitet</h3>',
        ),
        "BrazilPage.tsx": (
            '<span className="label">MARKEDSFORVENTNINGER</span><h2>',
            '<span className="label">ALLE INDIKATORER</span><h2>',
            '<span className="label">FULL MAKROKALENDER</span><h2>',
            '<span className="label">KILDER OG METODE</span><h2>',
        ),
        "CashPage.tsx": (
            '<span className="label">BEGRENSNING</span>',
            '<h3>{buybackConstraintTitle}</h3>',
        ),
        "ConsensusPage.tsx": (
            '<span className="label">DETALJER</span><h2>Analytikere og kursmål</h2>',
            '<span className="label">DETALJER</span><h2>Beat/miss per kvartal</h2>',
            '<span className="label">DETALJER</span><h2>Kilder og metode</h2>',
        ),
        "DataQualityPage.tsx": (
            '<span className="label">TEKNISK DIAGNOSTIKK</span>',
            '<h2>Oppdateringsjobber, cache og preflight</h2>',
            '<h3>Preflight</h3>',
        ),
    }

    for page_file, headings in expected_headings.items():
        page = source(page_file)
        for heading in headings:
            assert heading in page, f"{heading} mangler i {page_file}"


def test_buyback_subsections_follow_their_h2_section() -> None:
    page = source("BuybackPage.tsx")
    section_start = page.index("Hvordan programmet faktisk gjennomføres")
    subsection = page[section_start:]

    assert subsection.count("<h3") == 4
    assert "<h2>Faktisk gjennomføring</h2>" not in subsection


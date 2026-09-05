from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bemobi_primary_view_focuses_on_operations_and_valuation() -> None:
    page = (ROOT / "frontend/src/BemobiPageBase.tsx").read_text(encoding="utf-8")
    wrapper = (ROOT / "frontend/src/BemobiPage.tsx").read_text(encoding="utf-8")
    financials = (ROOT / "cloudflare/src/bemobi_cvm_financials.py").read_text(encoding="utf-8")

    for label in (
        "Hvordan går Bemobi operasjonelt?",
        "Omsetning",
        "Justert EBITDA",
        "EBITDA-margin",
        "Justert resultat",
        "VEKSTDRIVERE",
        "Payments",
        "SaaS",
        "KONTANTGENERERING",
        "Hva betaler markedet?",
        "P/E TTM",
        "EV / EBIT",
        "FCF yield",
        "KVARTALSUTVIKLING",
        "Siste fire rapporterte kvartaler",
        "Det viktigste å følge",
    ):
        assert label in page

    for removed_label in (
        "Otellos eierandel",
        "Bemobi-posten",
        "Estimert utbytte til Otello",
        "Kapitalretur · skatt",
        "BemobiSourceStatusPanel",
        "Capex-avstemming",
    ):
        assert removed_label not in page
        assert removed_label not in wrapper

    assert 'completeTtm(quarters, "reported_net_income_parent_mbrl")' in page
    assert 'completeTtm(quarters, "reported_ebit_mbrl")' in page
    assert 'completeTtm(quarters, "reported_operating_cash_flow_mbrl")' in page
    assert 'completeTtm(quarters, "reported_capex_cash_outflow_mbrl")' in page

    assert 'CAPEX_FIELD = "reported_capex_cash_outflow_mbrl"' in financials
    assert 'CAPEX_SELECTION = "CVM_DFC_DESCRIPTION_MATCH"' in financials
    assert "parse_capex_accounts_archive" in financials
    assert "CAPEX_ASSET_TOKENS" in financials

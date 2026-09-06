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
        "P/E {forwardLabel}",
        "EV / EBITDA {forwardLabel}",
        "Est. payout yield",
        "OpFCF yield TTM",
        "Net cash / MCap",
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
        "CVM CFO − capex når komplett",
    ):
        assert removed_label not in page
        assert removed_label not in wrapper

    assert 'completeTtm(quarters, "reported_net_income_parent_mbrl")' in page
    assert 'completeTtm(quarters, "adjusted_ebitda_mbrl")' in page
    assert 'fetchPreloadedJson<BemobiConsensus>("/api/bemobi/consensus")' in page
    assert "selectForwardEstimate" in page
    assert "adjusted_fcf_yield_pct" in page
    assert "earnings_yield_pct" in page

    assert 'CAPEX_FIELD = "reported_capex_cash_outflow_mbrl"' in financials
    assert 'CAPEX_SELECTION = "CVM_DFC_DESCRIPTION_MATCH"' in financials
    assert "parse_capex_accounts_archive" in financials
    assert "CAPEX_ASSET_TOKENS" in financials

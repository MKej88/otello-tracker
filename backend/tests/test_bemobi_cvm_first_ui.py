from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bemobi_primary_view_prefers_economic_revenue_and_reconciles_cvm_controls() -> None:
    page = (ROOT / "frontend/src/BemobiPage.tsx").read_text(encoding="utf-8")
    source_status = (ROOT / "frontend/src/BemobiSourceStatusPanel.tsx").read_text(encoding="utf-8")
    financials = (ROOT / "cloudflare/src/bemobi_cvm_financials.py").read_text(encoding="utf-8")

    assert "Verdsettelse nå · CVM-first" in page
    assert "TTM-grunnlag · Bemobi + CVM" in page
    assert "Harmonisert nettoomsetning TTM · Bemobi/CVM release" in page
    assert "Regnskapsført omsetning TTM · CVM 3.01 · kontroll" in page
    assert "Rapportert EBIT TTM · CVM 3.05" in page
    assert "Rapportert resultat TTM · CVM 3.11.01" in page
    assert "Operasjonell kontantstrøm TTM · CVM 6.01" in page
    assert "Capex TTM · CVM DFC" in page
    assert "FCF TTM · CVM CFO − capex" in page
    assert "Harmonisert nettoomsetning" in page
    assert "Regnskapsført omsetning" in page
    assert "Resultat til Bemobi-aksjonærer" in page
    assert "Capex-avstemming" in page
    assert "Justert fallback" in page

    assert 'CAPEX_FIELD = "reported_capex_cash_outflow_mbrl"' in financials
    assert 'CAPEX_SELECTION = "CVM_DFC_DESCRIPTION_MATCH"' in financials
    assert "parse_capex_accounts_archive" in financials
    assert "CAPEX_ASSET_TOKENS" in financials
    assert "Capex TTM · CVM DFC" in source_status
    assert "Capex-konto i siste filing" in source_status
    assert "FCF TTM · CFO minus capex" in source_status

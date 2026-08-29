from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bemobi_primary_view_prefers_cvm_and_reconciles_capex() -> None:
    page = (ROOT / "frontend/src/BemobiPage.tsx").read_text(encoding="utf-8")
    source_status = (ROOT / "frontend/src/BemobiSourceStatusPanel.tsx").read_text(encoding="utf-8")
    financials = (ROOT / "cloudflare/src/bemobi_cvm_financials.py").read_text(encoding="utf-8")

    assert "Verdsettelse nå · CVM-first" in page
    assert "TTM-grunnlag · CVM først" in page
    assert "Rapportert omsetning TTM · CVM 3.01" in page
    assert "Rapportert EBIT TTM · CVM 3.05" in page
    assert "Rapportert resultat TTM · CVM 3.11.01" in page
    assert "Operasjonell kontantstrøm TTM · CVM 6.01" in page
    assert "Capex TTM · CVM 6.02.02" in page
    assert "FCF TTM · CVM CFO − capex" in page
    assert "Rapportert omsetning" in page
    assert "Resultat til Bemobi-aksjonærer" in page
    assert "Capex-avstemming" in page
    assert "Justert fallback" in page

    assert '"reported_capex_cash_outflow_mbrl"' in financials
    assert '"account": "6.02.02"' in financials
    assert "Capex TTM · 6.02.02" in source_status
    assert "FCF TTM · CFO minus capex" in source_status

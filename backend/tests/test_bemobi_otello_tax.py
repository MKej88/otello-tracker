from __future__ import annotations

from app.bemobi import dashboard


def test_jcp_uses_otello_treaty_rate_not_generic_published_net() -> None:
    distribution = {
        "type": "JCP",
        "announcement_date": "2026-08-11",
        "gross_per_share_brl": 1.0,
        "net_per_share_brl": 0.825,
        "otello_gross_mbrl": 10.0,
        "otello_net_mbrl": 8.25,
        "tax_treatment": "generic 17.5% withholding",
    }
    result = dashboard._apply_distribution_tax(distribution)
    assert result is not None
    assert result["net_per_share_brl"] == 0.825
    assert result["otello_net_mbrl"] == 8.25
    assert result["otello_withholding_rate_pct"] == 15.0
    assert result["otello_net_per_share_brl"] == 0.85
    assert result["otello_treaty_net_mbrl"] == 8.5


def test_ordinary_2026_dividend_uses_ten_percent_brazil_withholding() -> None:
    distribution = {
        "type": "DIVIDEND",
        "announcement_date": "2026-12-15",
        "gross_per_share_brl": 2.0,
        "otello_gross_mbrl": 20.0,
    }
    result = dashboard._apply_distribution_tax(distribution)
    assert result is not None
    assert result["otello_withholding_rate_pct"] == 10.0
    assert result["otello_net_per_share_brl"] == 1.8
    assert result["otello_treaty_net_mbrl"] == 18.0


def test_pre_2026_approved_dividend_is_grandfathered_at_zero_percent() -> None:
    distribution = {
        "type": "DIVIDEND",
        "announcement_date": "2025-12-18",
        "payment_date": "2026-01-15",
        "gross_per_share_brl": 1.0,
        "otello_gross_mbrl": 10.0,
    }
    result = dashboard._apply_distribution_tax(distribution)
    assert result is not None
    assert result["otello_withholding_rate_pct"] == 0.0
    assert result["otello_treaty_net_mbrl"] == 10.0


def test_distribution_estimate_exposes_dividend_and_jcp_net_scenarios() -> None:
    estimate = {
        "ready": True,
        "otello_gross_mbrl": 100.0,
        "otello_gross_mnok": 200.0,
        "otello_gross_per_otec_share_nok": 2.0,
        "methodology_note": "TTM run-rate.",
    }
    result = dashboard._apply_estimate_tax(estimate)
    assert result is not None
    assert result["ordinary_dividend_withholding_rate_pct"] == 10.0
    assert result["jcp_withholding_rate_pct"] == 15.0
    assert result["otello_net_dividend_mbrl"] == 90.0
    assert result["otello_net_jcp_mbrl"] == 85.0
    assert result["otello_net_dividend_mnok"] == 180.0
    assert result["otello_net_jcp_mnok"] == 170.0
    assert result["otello_net_dividend_per_otec_share_nok"] == 1.8
    assert result["otello_net_jcp_per_otec_share_nok"] == 1.7
    assert result["norwegian_cash_tax_modeled"] is False
    assert "10 %" in result["methodology_note"]
    assert "15 %" in result["methodology_note"]


def test_cloudflare_overlay_keeps_same_tax_model() -> None:
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "cloudflare"
        / "src"
        / "bemobi_dashboard.py"
    ).read_text(encoding="utf-8")
    assert "OTELLO_BRAZIL_DIVIDEND_WITHHOLDING_PCT = 10.0" in source
    assert "OTELLO_BRAZIL_JCP_WITHHOLDING_PCT = 15.0" in source
    assert '"otello_treaty_net_mbrl"' in source
    assert '"otello_net_dividend_mnok"' in source
    assert '"otello_net_jcp_mnok"' in source


def test_frontend_renders_net_tax_scenarios() -> None:
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "BemobiPage.tsx"
    ).read_text(encoding="utf-8")
    assert "Netto · ordinært utbytte" in source
    assert "Netto · JCP" in source
    assert "Otello-spesifikk sats" in source
    assert "otello_treaty_net_mbrl" in source
    assert "Publisert netto per Bemobi-aksje · generell sats" in source

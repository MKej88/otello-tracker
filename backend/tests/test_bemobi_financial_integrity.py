from __future__ import annotations

import sys
from pathlib import Path

from app.bemobi.dashboard import _valuation_payload as reference_valuation_payload

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from bemobi_dashboard import _valuation_payload as worker_valuation_payload  # noqa: E402
from bemobi_web_refresh import (  # noqa: E402
    _valuation_anchor_from_result,
    parse_bemobi_result_text,
)


def _ownership() -> dict:
    return {"bemobi_total_shares": 85_608_392}


def _quarters(last_period: str = "2Q26") -> list[dict]:
    rows = [
        {"period": "3Q25", "adjusted_net_income_mbrl": 41.0, "adjusted_ebitda_mbrl": 62.7, "adjusted_cash_generation_mbrl": 47.5, "source": "XP"},
        {"period": "4Q25", "adjusted_net_income_mbrl": 61.0, "adjusted_ebitda_mbrl": 66.0, "adjusted_cash_generation_mbrl": 52.5, "source": "XP"},
        {"period": "1Q26", "adjusted_net_income_mbrl": 37.0, "adjusted_ebitda_mbrl": 75.0, "adjusted_cash_generation_mbrl": 61.4, "source": "Bemobi"},
        {"period": "2Q26", "adjusted_net_income_mbrl": 45.2, "adjusted_ebitda_mbrl": 79.4, "adjusted_cash_generation_mbrl": 64.8, "source": "Bemobi"},
    ]
    if last_period == "3Q26":
        rows = rows[1:] + [
            {"period": "3Q26", "adjusted_net_income_mbrl": 48.0, "adjusted_ebitda_mbrl": 84.0, "adjusted_cash_generation_mbrl": 68.0, "source": "Bemobi"}
        ]
    return rows


def _anchor(period: str = "2Q26") -> dict:
    return {
        "period": period,
        "ttm_ebit_mbrl": 175.08,
        "net_debt_mbrl": -287.2,
        "quality": "CVM_DERIVED_APPROX",
        "source": "CVM-derived",
    }


def test_current_ev_anchor_keeps_ev_metrics_in_reference_and_worker() -> None:
    for builder in (reference_valuation_payload, worker_valuation_payload):
        valuation = builder(22.8, _ownership(), _quarters(), _anchor())
        assert valuation["period"] == "TTM 3Q25–2Q26"
        assert valuation["ttm_end_period"] == "2Q26"
        assert valuation["ev_anchor_status"] == "CURRENT"
        assert valuation["ev_anchor_is_current"] is True
        assert valuation["enterprise_value_mbrl"] is not None
        assert valuation["ev_ebit_ttm"] is not None
        assert valuation["net_cash_mbrl"] == 287.2


def test_stale_ev_anchor_fails_closed_without_hiding_period_fact() -> None:
    for builder in (reference_valuation_payload, worker_valuation_payload):
        valuation = builder(22.8, _ownership(), _quarters("3Q26"), _anchor("2Q26"))
        assert valuation["period"] == "TTM 4Q25–3Q26"
        assert valuation["ttm_end_period"] == "3Q26"
        assert valuation["ev_anchor_period"] == "2Q26"
        assert valuation["ev_anchor_status"] == "STALE"
        assert valuation["ev_anchor_is_current"] is False
        assert valuation["ev_metrics_ready"] is False
        assert valuation["enterprise_value_mbrl"] is None
        assert valuation["ev_ebit_ttm"] is None
        assert valuation["net_cash_mbrl"] == 287.2
        assert valuation["pe_ttm"] is not None
        assert "skjules" in valuation["methodology_note"]


def test_result_parser_captures_growth_fields_and_explicit_ev_anchor_inputs() -> None:
    text = """
    BEMOBI MOBILE TECH S.A. 3T26
    Receita Líquida 250,0 200,0 25,0%
    EBITDA Ajustado 86,0 68,8 25,0%
    Margem EBITDA Ajustado 34,4%
    Lucro Líquido Ajustado 49,0 39,2 25,0%
    EBITDA Ajustado - Capex 70,0
    Cash Conversion 81,4%
    Posição de Caixa 360,0
    Payments 60,0% ano/ano
    SaaS 22,0% ano/ano
    EBIT TTM 190,0
    Net Cash 310,0
    """

    result = parse_bemobi_result_text(text, published_date="2026-11-10")

    assert result["period"] == "3Q26"
    assert result["adjusted_net_revenue_yoy_pct"] == 25.0
    assert result["adjusted_ebitda_yoy_pct"] == 25.0
    assert result["adjusted_net_income_yoy_pct"] == 25.0
    assert result["payments_yoy_pct"] == 60.0
    assert result["saas_yoy_pct"] == 22.0
    assert result["ttm_ebit_mbrl"] == 190.0
    assert result["net_debt_mbrl"] == -310.0

    anchor = _valuation_anchor_from_result(
        result,
        source_name="CVM",
        source_url="https://example.test/bemobi-3q26.pdf",
    )
    assert anchor == {
        "period": "3Q26",
        "ttm_ebit_mbrl": 190.0,
        "net_debt_mbrl": -310.0,
        "cash_position_mbrl": 360.0,
        "quality": "OFFICIAL_RESULT_AUTO",
        "source": "CVM",
        "source_url": "https://example.test/bemobi-3q26.pdf",
    }


def test_result_without_explicit_ev_inputs_does_not_invent_anchor() -> None:
    text = """
    BEMOBI MOBILE TECH S.A. 3T26
    Receita Líquida 250,0 200,0 25,0%
    EBITDA Ajustado 86,0 68,8 25,0%
    Lucro Líquido Ajustado 49,0 39,2 25,0%
    EBITDA Ajustado - Capex 70,0
    """
    result = parse_bemobi_result_text(text, published_date="2026-11-10")
    assert result["ttm_ebit_mbrl"] is None
    assert result["net_debt_mbrl"] is None
    assert _valuation_anchor_from_result(result, source_name="CVM", source_url="https://example.test/result.pdf") is None

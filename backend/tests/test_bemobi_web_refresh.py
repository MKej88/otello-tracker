from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from bemobi_web_refresh import (  # noqa: E402
    parse_analyst_coverage_html,
    parse_bemobi_result_text,
    parse_marketscreener_finances_html,
    parse_ownership_html,
    parse_xp_preview_html,
)


def test_official_ir_ownership_parser_validates_share_math() -> None:
    html = """
    <table>
      <tr><th>Acionista</th><th>Ações Ordinárias</th><th>%</th></tr>
      <tr><td>Otello Technology Investiment AS</td><td>32.719.588</td><td>38,220%</td></tr>
      <tr><td>Pedro Santos Ripper</td><td>5.239.323</td><td>6,120%</td></tr>
      <tr><td>Total</td><td>85.608.392</td><td>100,000%</td></tr>
    </table>
    """
    result = parse_ownership_html(html, checked_date="2026-08-20")
    assert result == {
        "shares": 32_719_588,
        "ownership_pct": 38.22,
        "bemobi_total_shares": 85_608_392,
        "checked_date": "2026-08-20",
        "quality": "OFFICIAL_IR_AUTO",
    }


def test_official_ir_ownership_parser_fails_closed_on_bad_percentage() -> None:
    html = """
    <table>
      <tr><td>Otello Technology Investiment AS</td><td>32.719.588</td><td>25,000%</td></tr>
      <tr><td>Total</td><td>85.608.392</td><td>100,000%</td></tr>
    </table>
    """
    try:
        parse_ownership_html(html, checked_date="2026-08-20")
    except ValueError as exc:
        assert "stemmer ikke" in str(exc)
    else:
        raise AssertionError("Parseren skal avvise inkonsistent eierandel")


def test_official_ir_analyst_parser_handles_portuguese_dates_and_ratings() -> None:
    html = """
    <table>
      <tr><th>Instituição</th><th>Nome do Analista</th><th>Email</th><th>Recomendação</th><th>Última Atualização</th><th>Preço Alvo</th></tr>
      <tr><td>BTG Pactual</td><td>Osni Carfi</td><td>x@example.com</td><td>Compra</td><td>11-Nov-25</td><td>R$35,00</td></tr>
      <tr><td>Itaú BBA</td><td>Maria Clara Infantozzi</td><td>x@example.com</td><td>Compra</td><td>15-Abr-26</td><td>R$33,80</td></tr>
      <tr><td>Morgan Stanley</td><td>Cesar Medina</td><td>x@example.com</td><td>Manutenção</td><td>11-Jun-26</td><td>R$24,00</td></tr>
      <tr><td>XP</td><td>Bernardo Guttmann</td><td>x@example.com</td><td>Compra</td><td>30-Mar-26</td><td>R$31,00</td></tr>
    </table>
    """
    rows = parse_analyst_coverage_html(html)
    assert [row["institution"] for row in rows] == ["BTG Pactual", "Itaú BBA", "Morgan Stanley", "XP"]
    assert rows[0]["last_update"] == "2025-11-11"
    assert rows[1]["target_price_brl"] == 33.8
    assert rows[2]["rating"] == "HOLD"


def test_marketscreener_parser_extracts_complete_forward_years() -> None:
    html = """
    <table>
      <tr><th></th><th>2025</th><th>2026</th><th>2027</th></tr>
      <tr><td>Net sales</td><td>700</td><td>814</td><td>1,002</td></tr>
      <tr><td>EBITDA</td><td>250</td><td>288.2</td><td>342.5</td></tr>
      <tr><td>EBIT</td><td>180</td><td>205.4</td><td>257.1</td></tr>
      <tr><td>Net income</td><td>160</td><td>174.3</td><td>191.6</td></tr>
      <tr><td>EPS</td><td>1.90</td><td>2.07</td><td>2.16</td></tr>
      <tr><td>Net debt</td><td>-200</td><td>-226</td><td>-208</td></tr>
    </table>
    """
    years = parse_marketscreener_finances_html(html)
    assert years[0]["year"] == 2026
    assert years[0]["revenue_mbrl"] == 814.0
    assert years[0]["net_debt_mbrl"] == -226.0
    assert years[1]["revenue_mbrl"] == 1002.0
    assert years[1]["ebit_mbrl"] == 257.1


def test_result_parser_extracts_required_official_quarter_metrics() -> None:
    text = """
    BEMOBI MOBILE TECH S.A. 2T26
    Receita Líquida 227,3 175,1 29,8%
    EBITDA Ajustado 79,4 59,8 32,7%
    Margem EBITDA Ajustado 34,9%
    Lucro Líquido Ajustado 45,2 34,7 30,1%
    EBITDA Ajustado - Capex 64,8
    Cash Conversion 81,5%
    Posição de Caixa 328,0
    """
    result = parse_bemobi_result_text(text, published_date="2026-08-11")
    assert result["period"] == "2Q26"
    assert result["period_end"] == "2026-06-30"
    assert result["adjusted_net_revenue_mbrl"] == 227.3
    assert result["adjusted_ebitda_mbrl"] == 79.4
    assert result["adjusted_net_income_mbrl"] == 45.2
    assert result["ebitda_less_capex_mbrl"] == 64.8
    assert result["adjusted_ebitda_margin_pct"] == 34.9
    assert result["cash_conversion_pct"] == 81.5
    assert result["cash_mbrl"] == 328.0


def test_result_parser_refuses_document_without_bemobi_signature() -> None:
    try:
        parse_bemobi_result_text(
            "2T26 Receita Líquida 227,3 EBITDA Ajustado 79,4 Lucro Líquido Ajustado 45,2 EBITDA Ajustado - Capex 64,8",
            published_date="2026-08-11",
        )
    except ValueError as exc:
        assert "signatur" in str(exc)
    else:
        raise AssertionError("Feil utsteder skal avvises")


def test_xp_preview_parser_is_best_effort_and_requires_preview_context() -> None:
    html = """
    <html><head><meta property="article:published_time" content="2026-10-20T12:00:00-03:00"></head>
    <body>
      <h1>BMOB3: prévia do 3T26</h1>
      <p>Esperamos receita líquida de R$ 250,0 milhões, EBITDA ajustado de R$ 86,0 milhões e lucro líquido ajustado de R$ 49,0 milhões.</p>
    </body></html>
    """
    preview = parse_xp_preview_html(html)
    assert preview is not None
    assert preview["period"] == "3Q26"
    assert preview["published_date"] == "2026-10-20"
    metrics = {item["metric"]: item["value_mbrl"] for item in preview["estimates"]}
    assert metrics["adjusted_ebitda_mbrl"] == 86.0
    assert metrics["adjusted_net_income_mbrl"] == 49.0


def test_production_workflow_contains_bemobi_web_refresh_step() -> None:
    entry = (ROOT / "cloudflare/src/entry.py").read_text(encoding="utf-8")
    full_refresh = (ROOT / "cloudflare/src/full_refresh.py").read_text(encoding="utf-8")
    assert "from bemobi_web_refresh import refresh_bemobi_web" in entry
    assert '"refresh Bemobi investor web facts"' in entry
    assert 'source_results["bemobi_web"]' in entry
    assert '"bemobi_web": "BEMOBI_IR"' in full_refresh

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.dashboard import dashboard_summary
from app.dashboard_freshness import enrich_dashboard_summary
from app.db.connection import get_connection

# Curated from Bemobi's 2Q26 results release. The production service links the metrics to
# the newest official CVM RESULTS document when that metadata is available in company_news.
LATEST_RESULT = {
    "period": "2Q26",
    "period_end": "2026-06-30",
    "published_date": "2026-08-11",
    "adjusted_net_revenue_mbrl": 227.3,
    "adjusted_net_revenue_yoy_pct": 29.8,
    "adjusted_ebitda_mbrl": 79.4,
    "adjusted_ebitda_yoy_pct": 32.7,
    "adjusted_ebitda_margin_pct": 34.9,
    "adjusted_net_income_mbrl": 45.2,
    "adjusted_net_income_yoy_pct": 30.1,
    "ebitda_less_capex_mbrl": 64.8,
    "cash_conversion_pct": 81.5,
    "cash_mbrl": 328.0,
    "payments_yoy_pct": 75.0,
    "saas_yoy_pct": 21.0,
    "quality": "CURATED_FROM_RESULTS_RELEASE",
}

CURRENT_OWNERSHIP = {
    "shares": 32_719_588,
    "ownership_pct": 38.220,
    "bemobi_total_shares": 85_608_392,
    "checked_date": "2026-08-19",
    "quality": "OFFICIAL_IR_CURRENT",
}

# The cash-generation metric follows Bemobi's own non-GAAP definition: adjusted EBITDA
# less tangible/intangible investments, excluding right-of-use capex. It is an operating
# FCF proxy and is deliberately labelled adjusted FCF in the investor UI.
TTM_QUARTERS = [
    {
        "period": "3Q25",
        "adjusted_net_income_mbrl": 41.0,
        "adjusted_ebitda_mbrl": 62.7,
        "adjusted_cash_generation_mbrl": 47.5,
        "source": "XP",
        "source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-revisao-do-3t25-resultados-fortes-superando-expectativas-e-acelerando-a-receita/",
    },
    {
        "period": "4Q25",
        "adjusted_net_income_mbrl": 61.0,
        "adjusted_ebitda_mbrl": 66.0,
        "adjusted_cash_generation_mbrl": 52.5,
        "source": "XP / CVM",
        "source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-execucao-segue-solida-sustentando-crescimento-consistente-e-forte-geracao-de-caixa/",
    },
    {
        "period": "1Q26",
        "adjusted_net_income_mbrl": 37.0,
        "adjusted_ebitda_mbrl": 75.0,
        "adjusted_cash_generation_mbrl": 61.4,
        "source": "Bemobi / CVM",
        "source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-surpresa-positiva-solida-com-pagamentos-e-saas-impulsionando-o-crescimento/",
    },
    {
        "period": "2Q26",
        "adjusted_net_income_mbrl": 45.2,
        "adjusted_ebitda_mbrl": 79.4,
        "adjusted_cash_generation_mbrl": 64.8,
        "source": "Bemobi/CVM",
        "source_url": None,
    },
]

# Standardised accounting EBIT for the last four reported quarters through 2Q26, based on
# CVM-derived financial statements. Net debt is an approximate 2Q26 CVM-derived anchor;
# negative means net cash. Keeping the quality flag visible prevents false precision.
TTM_EBIT_MBRL = 175.08
NET_DEBT_2Q26_MBRL = -287.2
EV_ANCHOR = {
    "period": "2Q26",
    "ttm_ebit_mbrl": TTM_EBIT_MBRL,
    "net_debt_mbrl": NET_DEBT_2Q26_MBRL,
    "cash_position_mbrl": 328.0,
    "quality": "CVM_DERIVED_APPROX",
    "source": "CVM-derived / Bemobi 2Q26",
    "source_url": "https://sabbius.com.br/company/show/BMOB3",
}

VALUATION_MULTIPLES = (12.0, 14.0, 16.0)

RESULTS_FALLBACK_URL = "https://ri.bemobi.com.br/informacoes-financeiras/resultados-trimestrais/"
OWNERSHIP_URL = "https://ri.bemobi.com.br/governanca/composicao-acionaria/"
EVENTS_URL = "https://ri.bemobi.com.br/nossas-acoes/calendario-de-eventos/"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (ValueError, ArithmeticError):
        return None


def _latest_distribution(connection) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT ca.action_type, ca.announcement_date, ca.record_date, ca.ex_date,
               ca.payment_date,
               COALESCE(ca.gross_amount_per_share, ca.amount_per_share) AS gross_per_share,
               ca.net_amount_per_share AS net_per_share,
               COALESCE(ca.gross_total_amount, ca.total_amount) AS gross_total,
               ca.net_total_amount AS net_total,
               ca.withholding_rate, ca.tax_treatment, ca.external_action_id,
               sd.url AS source_url, s.code AS source_code, sd.title AS source_title
        FROM corporate_actions ca
        JOIN instruments i ON i.id = ca.issuer_instrument_id
        JOIN source_documents sd ON sd.id = ca.source_document_id
        JOIN sources s ON s.id = sd.source_id
        WHERE i.symbol = 'BMOB3'
          AND ca.action_type IN ('DIVIDEND', 'JCP', 'DISTRIBUTION')
        ORDER BY COALESCE(ca.ex_date, ca.record_date, ca.announcement_date, ca.payment_date) DESC,
                 ca.id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row is not None else None


def _latest_result_source(connection) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT cn.published_at, cn.headline, sd.url, sd.title, s.code AS source_code
        FROM company_news cn
        JOIN instruments i ON i.id = cn.issuer_instrument_id
        JOIN source_documents sd ON sd.id = cn.source_document_id
        JOIN sources s ON s.id = sd.source_id
        WHERE i.symbol = 'BMOB3' AND cn.category = 'RESULTS'
        ORDER BY COALESCE(cn.published_at, sd.published_at) DESC, cn.id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row is not None else None


def _distribution_payload(row: dict[str, Any] | None, holding_shares: int | None) -> dict[str, Any] | None:
    if row is None:
        return None
    gross_per_share = _number(row.get("gross_per_share"))
    net_per_share = _number(row.get("net_per_share"))
    gross_total = _number(row.get("gross_total"))
    net_total = _number(row.get("net_total"))
    withholding = _number(row.get("withholding_rate"))
    holding = int(holding_shares or 0)
    return {
        "type": row.get("action_type"),
        "announcement_date": row.get("announcement_date"),
        "record_date": row.get("record_date"),
        "ex_date": row.get("ex_date"),
        "payment_date": row.get("payment_date"),
        "gross_per_share_brl": gross_per_share,
        "net_per_share_brl": net_per_share,
        "gross_total_mbrl": None if gross_total is None else gross_total / 1_000_000,
        "net_total_mbrl": None if net_total is None else net_total / 1_000_000,
        "withholding_rate_pct": None if withholding is None else withholding * 100,
        "tax_treatment": row.get("tax_treatment"),
        "otello_gross_mbrl": None if gross_per_share is None or holding <= 0 else gross_per_share * holding / 1_000_000,
        "otello_net_mbrl": None if net_per_share is None or holding <= 0 else net_per_share * holding / 1_000_000,
        "source_code": row.get("source_code"),
        "source_url": row.get("source_url"),
        "source_title": row.get("source_title"),
        "external_action_id": row.get("external_action_id"),
    }


def _valuation_payload(price_brl: float | None, result_url: str) -> dict[str, Any]:
    total_shares = int(CURRENT_OWNERSHIP["bemobi_total_shares"])
    ttm_net_income = sum(float(item["adjusted_net_income_mbrl"]) for item in TTM_QUARTERS)
    ttm_ebitda = sum(float(item["adjusted_ebitda_mbrl"]) for item in TTM_QUARTERS)
    ttm_adjusted_fcf = sum(float(item["adjusted_cash_generation_mbrl"]) for item in TTM_QUARTERS)
    ttm_ebit = float(EV_ANCHOR["ttm_ebit_mbrl"])
    net_debt = float(EV_ANCHOR["net_debt_mbrl"])
    adjusted_eps = ttm_net_income * 1_000_000 / total_shares

    market_cap_mbrl = None
    enterprise_value_mbrl = None
    pe_ttm = None
    price_to_ebitda_ttm = None
    earnings_yield_pct = None
    adjusted_fcf_yield_pct = None
    ev_ebit_ttm = None
    scenarios: list[dict[str, Any]] = []

    if price_brl is not None and price_brl > 0:
        market_cap_mbrl = price_brl * total_shares / 1_000_000
        enterprise_value_mbrl = market_cap_mbrl + net_debt
        pe_ttm = market_cap_mbrl / ttm_net_income
        price_to_ebitda_ttm = market_cap_mbrl / ttm_ebitda
        earnings_yield_pct = ttm_net_income / market_cap_mbrl * 100
        adjusted_fcf_yield_pct = ttm_adjusted_fcf / market_cap_mbrl * 100
        ev_ebit_ttm = enterprise_value_mbrl / ttm_ebit if enterprise_value_mbrl > 0 else None
        scenarios = [
            {
                "multiple": multiple,
                "implied_price_brl": adjusted_eps * multiple,
                "upside_pct": (adjusted_eps * multiple / price_brl - 1) * 100,
            }
            for multiple in VALUATION_MULTIPLES
        ]

    source_quarters = []
    for item in TTM_QUARTERS:
        source_quarters.append(
            {
                **item,
                "source_url": result_url if item["period"] == "2Q26" else item["source_url"],
            }
        )

    return {
        "period": "TTM 3Q25–2Q26",
        "market_cap_mbrl": market_cap_mbrl,
        "enterprise_value_mbrl": enterprise_value_mbrl,
        "net_debt_mbrl": net_debt,
        "net_cash_mbrl": -net_debt,
        "ev_anchor_period": EV_ANCHOR["period"],
        "ev_anchor_quality": EV_ANCHOR["quality"],
        "ev_anchor_source": EV_ANCHOR["source"],
        "ev_anchor_source_url": EV_ANCHOR["source_url"],
        "adjusted_net_income_ttm_mbrl": ttm_net_income,
        "adjusted_ebitda_ttm_mbrl": ttm_ebitda,
        "adjusted_fcf_ttm_mbrl": ttm_adjusted_fcf,
        "ebit_ttm_mbrl": ttm_ebit,
        "adjusted_eps_ttm_brl": adjusted_eps,
        "pe_ttm": pe_ttm,
        "price_to_ebitda_ttm": price_to_ebitda_ttm,
        "earnings_yield_pct": earnings_yield_pct,
        "adjusted_fcf_yield_pct": adjusted_fcf_yield_pct,
        "ev_ebit_ttm": ev_ebit_ttm,
        "scenarios": scenarios,
        "source_quarters": source_quarters,
        "methodology_note": (
            "FCF yield (just.) bruker Bemobis egen justerte kontantgenerering, definert som "
            "justert EBITDA minus investeringer i materielle og immaterielle eiendeler (uten "
            "bruksrett-CAPEX). Det er en operasjonell FCF-proxy, ikke IFRS-kontantstrøm. "
            "EV/EBIT bruker standardisert EBIT TTM og et CVM-avledet netto kontantanker for 2Q26; "
            "netto kontantankeret er merket som omtrentlig. 12x/14x/16x er kun "
            "multipelsensitivitet, ikke kursmål."
        ),
    }


def bemobi_dashboard(database_path: str | None = None) -> dict[str, Any]:
    summary = enrich_dashboard_summary(dashboard_summary(database_path), database_path)
    if not summary.get("ready"):
        return {
            "ready": False,
            "reason": "dashboard_not_ready",
            "data_status": summary.get("data_status"),
        }

    with get_connection(database_path) as connection:
        distribution_row = _latest_distribution(connection)
        result_source = _latest_result_source(connection)

    nav_shares = int(summary.get("bemobi_shares") or 0)
    shares = nav_shares or int(CURRENT_OWNERSHIP["shares"])
    ownership_matches_nav = shares == int(CURRENT_OWNERSHIP["shares"])
    ownership_pct = (
        float(CURRENT_OWNERSHIP["ownership_pct"])
        if ownership_matches_nav
        else _number(summary.get("bemobi_ownership_pct"))
    )
    bmob3_price = _number(summary.get("bmob3_price"))
    brl_nok = _number(summary.get("brl_nok"))
    value_nok_m = _number(summary.get("bemobi_value_mnok"))
    value_brl_m = None if bmob3_price is None or shares <= 0 else bmob3_price * shares / 1_000_000

    outstanding_otello = int(summary.get("shares_outstanding") or 0)
    value_per_otello_share = None
    if value_nok_m is not None and outstanding_otello > 0:
        value_per_otello_share = value_nok_m * 1_000_000 / outstanding_otello

    market_dates = summary.get("market_timestamps") or {}
    result_url = str((result_source or {}).get("url") or RESULTS_FALLBACK_URL)
    result_source_code = str((result_source or {}).get("source_code") or "BEMOBI_IR")
    result_source_title = str(
        (result_source or {}).get("headline")
        or (result_source or {}).get("title")
        or "Bemobi 2Q26 resultater"
    )

    latest_result = {
        **LATEST_RESULT,
        "source_code": result_source_code,
        "source_url": result_url,
        "source_title": result_source_title,
    }
    distribution = _distribution_payload(distribution_row, shares)
    valuation = _valuation_payload(bmob3_price, result_url)

    sources = [
        {
            "label": "BMOB3-kurs",
            "source": summary.get("bmob3_price_source") or "B3",
            "url": None,
        },
        {
            "label": "Otellos Bemobi-eierandel",
            "source": "Bemobi IR",
            "url": OWNERSHIP_URL,
        },
        {
            "label": "2Q26 nøkkeltall",
            "source": result_source_code,
            "url": result_url,
        },
        {
            "label": "Verdsettelse TTM",
            "source": "3Q25–2Q26 rapporttall",
            "url": result_url,
        },
        {
            "label": "EV / EBIT og netto kontant",
            "source": EV_ANCHOR["source"],
            "url": EV_ANCHOR["source_url"],
        },
    ]
    if distribution is not None and distribution.get("source_url"):
        sources.append(
            {
                "label": "Utbytte / JCP",
                "source": distribution.get("source_code") or "CVM",
                "url": distribution.get("source_url"),
            }
        )

    return {
        "ready": True,
        "as_of_date": summary.get("as_of_date"),
        "market": {
            "price_brl": bmob3_price,
            "price_date": ((market_dates.get("bmob3") or {}).get("date")),
            "price_source": summary.get("bmob3_price_source"),
            "price_quality": summary.get("bmob3_price_quality"),
            "brl_nok": brl_nok,
            "brl_nok_date": ((market_dates.get("brl_nok") or {}).get("date")),
        },
        "otello": {
            "shares": shares or None,
            "ownership_pct": ownership_pct,
            "ownership_source_date": CURRENT_OWNERSHIP["checked_date"] if ownership_matches_nav else None,
            "ownership_quality": CURRENT_OWNERSHIP["quality"] if ownership_matches_nav else summary.get("bemobi_ownership_quality"),
            "bemobi_total_shares": CURRENT_OWNERSHIP["bemobi_total_shares"] if ownership_matches_nav else None,
            "value_brl_m": value_brl_m,
            "value_nok_m": value_nok_m,
            "value_per_otello_share_nok": value_per_otello_share,
        },
        "valuation": valuation,
        "latest_result": latest_result,
        "latest_distribution": distribution,
        "next_report": {
            "period": "3Q26",
            "date": None,
            "date_quality": "NOT_CONFIRMED",
            "label": "Dato ikke bekreftet av Bemobi",
            "source_url": EVENTS_URL,
        },
        "sources": sources,
        "note": (
            "BMOB3 og markedsverdi følger NAV-grunnlaget. Eierandelen 38,22 % er kontrollert "
            "mot Bemobis offisielle aksjonærside 19.08.2026. Verdsettelsen bruker rapporterte "
            "3Q25–2Q26-tall og oppdateres med løpende BMOB3-kurs."
        ),
    }

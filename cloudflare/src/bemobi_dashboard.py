from __future__ import annotations

from decimal import Decimal
from typing import Any

from dashboard_service import dashboard_summary, enrich_dashboard_summary

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


async def _latest_distribution(repository) -> dict[str, Any] | None:
    return await repository.first(
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
    )


async def _latest_result_source(repository) -> dict[str, Any] | None:
    return await repository.first(
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
    )


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


async def bemobi_dashboard(repository) -> dict[str, Any]:
    summary = await enrich_dashboard_summary(await dashboard_summary(repository), repository)
    if not summary.get("ready"):
        return {
            "ready": False,
            "reason": "dashboard_not_ready",
            "data_status": summary.get("data_status"),
        }

    distribution_row = await _latest_distribution(repository)
    result_source = await _latest_result_source(repository)

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
            "mot Bemobis offisielle aksjonærside 19.08.2026. 2Q26-nøkkeltall er kuraterte "
            "rapporttall; neste resultatdato vises først når Bemobi har publisert en bekreftet dato."
        ),
    }

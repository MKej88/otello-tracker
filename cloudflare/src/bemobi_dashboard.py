from __future__ import annotations

from decimal import Decimal
from typing import Any

from bemobi_facts import latest_bemobi_fact, load_bemobi_facts, public_fact
from dashboard_service import dashboard_summary, enrich_dashboard_summary

# Modellparametre, ikke finansielle fakta. Bemobi-tall og kildeproveniens ligger i D1.
VALUATION_MULTIPLES = (12.0, 14.0, 16.0)


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


def _valuation_payload(
    price_brl: float | None,
    ownership: dict[str, Any],
    ttm_quarters: list[dict[str, Any]],
    ev_anchor: dict[str, Any],
) -> dict[str, Any]:
    total_shares = int(ownership.get("bemobi_total_shares") or 0)
    ttm_net_income = sum(float(item["adjusted_net_income_mbrl"]) for item in ttm_quarters)
    ttm_ebitda = sum(float(item["adjusted_ebitda_mbrl"]) for item in ttm_quarters)
    ttm_adjusted_fcf = sum(float(item["adjusted_cash_generation_mbrl"]) for item in ttm_quarters)
    anchor_ebit = float(ev_anchor["ttm_ebit_mbrl"])
    anchor_net_debt = float(ev_anchor["net_debt_mbrl"])
    adjusted_eps = None if total_shares <= 0 else ttm_net_income * 1_000_000 / total_shares

    first_period = str(ttm_quarters[0].get("period") or "")
    last_period = str(ttm_quarters[-1].get("period") or "")
    period = f"TTM {first_period}–{last_period}" if first_period and last_period else "TTM"
    ev_anchor_period = str(ev_anchor.get("period") or "")
    ev_anchor_is_current = bool(last_period and ev_anchor_period == last_period)

    market_cap_mbrl = None
    enterprise_value_mbrl = None
    pe_ttm = None
    price_to_ebitda_ttm = None
    earnings_yield_pct = None
    adjusted_fcf_yield_pct = None
    ev_ebit_ttm = None
    scenarios: list[dict[str, Any]] = []

    if price_brl is not None and price_brl > 0 and total_shares > 0:
        market_cap_mbrl = price_brl * total_shares / 1_000_000
        pe_ttm = market_cap_mbrl / ttm_net_income
        price_to_ebitda_ttm = market_cap_mbrl / ttm_ebitda
        earnings_yield_pct = ttm_net_income / market_cap_mbrl * 100
        adjusted_fcf_yield_pct = ttm_adjusted_fcf / market_cap_mbrl * 100
        if ev_anchor_is_current:
            enterprise_value_mbrl = market_cap_mbrl + anchor_net_debt
            ev_ebit_ttm = enterprise_value_mbrl / anchor_ebit if enterprise_value_mbrl > 0 else None
        if adjusted_eps is not None:
            scenarios = [
                {
                    "multiple": multiple,
                    "implied_price_brl": adjusted_eps * multiple,
                    "upside_pct": (adjusted_eps * multiple / price_brl - 1) * 100,
                }
                for multiple in VALUATION_MULTIPLES
            ]

    ev_note = (
        "EV/EBIT bruker standardisert EBIT TTM og netto kontant fra samme kvartalsanker som "
        "TTM-seriens sluttperiode."
        if ev_anchor_is_current
        else (
            f"EV-ankeret er {ev_anchor_period or 'uten periode'}, mens TTM-serien slutter i "
            f"{last_period or 'ukjent periode'}. Enterprise value og EV/EBIT skjules derfor "
            "til et nytt kildebelagt anker er tilgjengelig."
        )
    )

    return {
        "period": period,
        "ttm_end_period": last_period or None,
        "market_cap_mbrl": market_cap_mbrl,
        "enterprise_value_mbrl": enterprise_value_mbrl,
        "net_debt_mbrl": anchor_net_debt,
        "net_cash_mbrl": -anchor_net_debt,
        "ev_anchor_period": ev_anchor_period or None,
        "ev_anchor_status": "CURRENT" if ev_anchor_is_current else "STALE",
        "ev_anchor_is_current": ev_anchor_is_current,
        "ev_metrics_ready": ev_anchor_is_current,
        "ev_anchor_quality": ev_anchor.get("quality") or ev_anchor.get("_quality"),
        "ev_anchor_source": ev_anchor.get("source") or ev_anchor.get("_source_name"),
        "ev_anchor_source_url": ev_anchor.get("source_url") or ev_anchor.get("_source_url"),
        "adjusted_net_income_ttm_mbrl": ttm_net_income,
        "adjusted_ebitda_ttm_mbrl": ttm_ebitda,
        "adjusted_fcf_ttm_mbrl": ttm_adjusted_fcf,
        "ebit_ttm_mbrl": anchor_ebit,
        "adjusted_eps_ttm_brl": adjusted_eps,
        "pe_ttm": pe_ttm,
        "price_to_ebitda_ttm": price_to_ebitda_ttm,
        "earnings_yield_pct": earnings_yield_pct,
        "adjusted_fcf_yield_pct": adjusted_fcf_yield_pct,
        "ev_ebit_ttm": ev_ebit_ttm,
        "scenarios": scenarios,
        "source_quarters": [public_fact(item) for item in ttm_quarters],
        "methodology_note": (
            "FCF yield (just.) bruker Bemobis egen justerte kontantgenerering, definert som "
            "justert EBITDA minus investeringer i materielle og immaterielle eiendeler (uten "
            "bruksrett-CAPEX). Det er en operasjonell FCF-proxy, ikke IFRS-kontantstrøm. "
            + ev_note
            + " 12x/14x/16x er kun multipelsensitivitet, ikke kursmål."
        ),
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
    latest_result_fact = await latest_bemobi_fact(repository, "RESULT")
    ownership_fact = await latest_bemobi_fact(repository, "OWNERSHIP")
    ttm_quarters = (await load_bemobi_facts(repository, "TTM_QUARTER"))[-4:]
    ev_anchor = await latest_bemobi_fact(repository, "VALUATION_ANCHOR")
    next_quarter_fact = await latest_bemobi_fact(repository, "NEXT_QUARTER")

    if latest_result_fact is None or ownership_fact is None or ev_anchor is None or len(ttm_quarters) < 4:
        return {
            "ready": False,
            "reason": "bemobi_investor_facts_not_ready",
            "data_status": summary.get("data_status"),
        }

    ownership = public_fact(ownership_fact) or {}
    nav_shares = int(summary.get("bemobi_shares") or 0)
    curated_shares = int(ownership.get("shares") or 0)
    shares = nav_shares or curated_shares
    ownership_matches_nav = shares == curated_shares and curated_shares > 0
    ownership_pct = (
        _number(ownership.get("ownership_pct"))
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
    curated_result = public_fact(latest_result_fact) or {}
    result_url = str((result_source or {}).get("url") or latest_result_fact.get("_source_url") or "")
    result_source_code = str((result_source or {}).get("source_code") or latest_result_fact.get("_source_name") or "BEMOBI_IR")
    result_source_title = str(
        (result_source or {}).get("headline")
        or (result_source or {}).get("title")
        or f"Bemobi {curated_result.get('period') or ''} resultater".strip()
    )

    latest_result = {
        **curated_result,
        "source_code": result_source_code,
        "source_url": result_url,
        "source_title": result_source_title,
    }
    distribution = _distribution_payload(distribution_row, shares)
    valuation = _valuation_payload(bmob3_price, ownership_fact, ttm_quarters, ev_anchor)

    sources = [
        {
            "label": "BMOB3-kurs",
            "source": summary.get("bmob3_price_source") or "B3",
            "url": None,
        },
        {
            "label": "Otellos Bemobi-eierandel",
            "source": ownership_fact.get("_source_name"),
            "url": ownership_fact.get("_source_url"),
        },
        {
            "label": f"{curated_result.get('period') or 'Siste'} nøkkeltall",
            "source": result_source_code,
            "url": result_url,
        },
        {
            "label": "Verdsettelse TTM",
            "source": "Kuraterte kvartalstall i D1",
            "url": ttm_quarters[-1].get("source_url") or ttm_quarters[-1].get("_source_url"),
        },
        {
            "label": "EV / EBIT og netto kontant",
            "source": ev_anchor.get("source") or ev_anchor.get("_source_name"),
            "url": ev_anchor.get("source_url") or ev_anchor.get("_source_url"),
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

    next_quarter = public_fact(next_quarter_fact) or {}
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
            "ownership_source_date": ownership_fact.get("_as_of_date") if ownership_matches_nav else None,
            "ownership_quality": ownership_fact.get("_quality") if ownership_matches_nav else summary.get("bemobi_ownership_quality"),
            "bemobi_total_shares": int(ownership.get("bemobi_total_shares") or 0) or None,
            "value_brl_m": value_brl_m,
            "value_nok_m": value_nok_m,
            "value_per_otello_share_nok": value_per_otello_share,
        },
        "valuation": valuation,
        "latest_result": latest_result,
        "latest_distribution": distribution,
        "next_report": {
            "period": next_quarter.get("period"),
            "date": next_quarter.get("report_date"),
            "date_quality": next_quarter.get("date_quality"),
            "label": next_quarter.get("label"),
            "source_url": None if next_quarter_fact is None else next_quarter_fact.get("_source_url"),
        },
        "sources": sources,
        "note": (
            "BMOB3 og markedsverdi følger NAV-grunnlaget. Eierandel, rapporttall og "
            "verdsettelsesankre leses fra kildebelagte Bemobi-fakta i databasen."
        ),
    }
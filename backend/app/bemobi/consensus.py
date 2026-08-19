from __future__ import annotations

from typing import Any

from app.bemobi.dashboard import bemobi_dashboard


ANALYST_COVERAGE = [
    {
        "institution": "BTG Pactual",
        "analyst": "Osni Carfi",
        "rating": "BUY",
        "target_price_brl": 35.00,
        "last_update": "2025-11-11",
    },
    {
        "institution": "Itaú BBA",
        "analyst": "Maria Clara Infantozzi",
        "rating": "BUY",
        "target_price_brl": 33.80,
        "last_update": "2026-04-15",
    },
    {
        "institution": "Morgan Stanley",
        "analyst": "Cesar Medina",
        "rating": "HOLD",
        "target_price_brl": 24.00,
        "last_update": "2026-06-11",
    },
    {
        "institution": "XP",
        "analyst": "Bernardo Guttmann",
        "rating": "BUY",
        "target_price_brl": 31.00,
        "last_update": "2026-03-30",
    },
]

# Public aggregate estimates. These are intentionally kept separate from broker-specific
# estimates because the public source does not expose a complete house-by-house model.
FORWARD_CONSENSUS = [
    {
        "year": 2026,
        "revenue_mbrl": 814.0,
        "ebitda_mbrl": 288.2,
        "ebit_mbrl": 205.4,
        "net_income_mbrl": 174.3,
        "eps_brl": 2.07,
        "net_debt_mbrl": -226.0,
    },
    {
        "year": 2027,
        "revenue_mbrl": 1002.0,
        "ebitda_mbrl": 342.5,
        "ebit_mbrl": 257.1,
        "net_income_mbrl": 191.6,
        "eps_brl": 2.16,
        "net_debt_mbrl": -208.0,
    },
]

# Public XP previews are stored as a compact beat/miss history. This is deliberately not
# called market consensus; each row identifies the contributing broker and source.
BEAT_MISS_HISTORY = [
    {
        "period": "3Q25",
        "broker": "XP",
        "published_date": "2025-10-29",
        "source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-outro-trimestre-forte/",
        "metrics": [
            {"metric": "adjusted_ebitda_mbrl", "label": "Justert EBITDA", "estimate": 61.0, "actual": 62.7},
            {"metric": "adjusted_net_income_mbrl", "label": "Justert resultat", "estimate": 39.0, "actual": 41.0},
        ],
    },
    {
        "period": "4Q25",
        "broker": "XP",
        "published_date": "2026-02-01",
        "source_url": "https://conteudos.xpi.com.br/acoes/relatorios/brasil-tech-previa-4t25/",
        "metrics": [
            {"metric": "adjusted_ebitda_mbrl", "label": "Justert EBITDA", "estimate": 65.0, "actual": 66.0},
            {"metric": "adjusted_net_income_mbrl", "label": "Justert resultat ex-swap", "estimate": 52.0, "actual": 61.0},
        ],
    },
    {
        "period": "2Q26",
        "broker": "XP",
        "published_date": "2026-07-16",
        "source_url": "https://conteudos.xpi.com.br/acoes/relatorios/tmt-previa-do-2t26-lwsa3-e-bmob3/",
        "metrics": [
            {"metric": "adjusted_ebitda_mbrl", "label": "Justert EBITDA", "estimate": 77.0, "actual": 79.4},
            {"metric": "adjusted_net_income_mbrl", "label": "Justert resultat", "estimate": 32.0, "actual": 45.2},
        ],
    },
]

ANALYST_COVERAGE_URL = "https://ri.bemobi.com.br/nossas-acoes/cobertura-de-analistas-2/"
FORWARD_CONSENSUS_URL = "https://www.marketscreener.com/quote/stock/BEMOBI-MOBILE-TECH-S-A-119084218/finances/"
XP_MODEL_URL = "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-atualizacao-do-modelo-e-comentarios-do-nosso-ndr-com-o-cfo-e-ri-da-bemobi/"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _target_payload(price_brl: float | None) -> dict[str, Any]:
    targets = [float(item["target_price_brl"]) for item in ANALYST_COVERAGE]
    average = sum(targets) / len(targets)
    high = max(targets)
    low = min(targets)
    buy_count = sum(1 for item in ANALYST_COVERAGE if item["rating"] == "BUY")
    hold_count = sum(1 for item in ANALYST_COVERAGE if item["rating"] == "HOLD")
    sell_count = sum(1 for item in ANALYST_COVERAGE if item["rating"] == "SELL")
    upside = None if price_brl is None or price_brl <= 0 else (average / price_brl - 1) * 100
    return {
        "analyst_count": len(ANALYST_COVERAGE),
        "buy_count": buy_count,
        "hold_count": hold_count,
        "sell_count": sell_count,
        "buy_pct": buy_count / len(ANALYST_COVERAGE) * 100,
        "average_target_brl": average,
        "high_target_brl": high,
        "low_target_brl": low,
        "upside_to_average_pct": upside,
        "source": "Bemobi IR",
        "source_url": ANALYST_COVERAGE_URL,
        "checked_date": "2026-08-19",
    }


def _forward_payload(price_brl: float | None, total_shares: int | None) -> list[dict[str, Any]]:
    market_cap = None
    if price_brl is not None and price_brl > 0 and total_shares is not None and total_shares > 0:
        market_cap = price_brl * total_shares / 1_000_000

    payload: list[dict[str, Any]] = []
    for item in FORWARD_CONSENSUS:
        row = dict(item)
        net_debt = float(item["net_debt_mbrl"])
        ebitda = float(item["ebitda_mbrl"])
        ebit = float(item["ebit_mbrl"])
        net_income = float(item["net_income_mbrl"])
        enterprise_value = None if market_cap is None else market_cap + net_debt
        row.update(
            {
                "market_cap_mbrl": market_cap,
                "enterprise_value_mbrl": enterprise_value,
                "pe": None if market_cap is None or net_income <= 0 else market_cap / net_income,
                "earnings_yield_pct": None if market_cap is None or market_cap <= 0 else net_income / market_cap * 100,
                "ev_ebitda": None if enterprise_value is None or ebitda <= 0 else enterprise_value / ebitda,
                "ev_ebit": None if enterprise_value is None or ebit <= 0 else enterprise_value / ebit,
            }
        )
        payload.append(row)
    return payload


def _beat_miss_payload() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in BEAT_MISS_HISTORY:
        metrics = []
        for metric in item["metrics"]:
            estimate = float(metric["estimate"])
            actual = float(metric["actual"])
            metrics.append(
                {
                    **metric,
                    "beat_miss_pct": None if estimate == 0 else (actual / estimate - 1) * 100,
                }
            )
        rows.append({**item, "metrics": metrics})
    return rows


def bemobi_consensus(database_path: str | None = None) -> dict[str, Any]:
    bemobi = bemobi_dashboard(database_path)
    if not bemobi.get("ready"):
        return {
            "ready": False,
            "reason": "bemobi_dashboard_not_ready",
        }

    market = bemobi.get("market") or {}
    otello = bemobi.get("otello") or {}
    price_brl = _number(market.get("price_brl"))
    total_shares = int(otello.get("bemobi_total_shares") or 0) or None

    return {
        "ready": True,
        "as_of_date": market.get("price_date") or bemobi.get("as_of_date"),
        "market": {
            "price_brl": price_brl,
            "price_date": market.get("price_date"),
            "price_source": market.get("price_source"),
        },
        "coverage": _target_payload(price_brl),
        "analysts": ANALYST_COVERAGE,
        "forward_consensus": {
            "source": "MarketScreener",
            "source_url": FORWARD_CONSENSUS_URL,
            "checked_date": "2026-08-19",
            "quality": "PUBLIC_AGGREGATE",
            "analyst_count": None,
            "years": _forward_payload(price_brl, total_shares),
            "note": (
                "Offentlig aggregert årsprognose. Kilden viser ikke et komplett hus-for-hus "
                "estimatsett, så antall bidragsytere per linje vises ikke."
            ),
        },
        "next_quarter": {
            "period": "3Q26",
            "status": "WAITING_FOR_PUBLIC_ESTIMATES",
            "estimates": [],
            "tracked_metrics": [
                "Nettoomsetning",
                "Justert EBITDA",
                "EBITDA-margin",
                "Justert resultat",
                "EPS",
            ],
            "note": "Ingen verifiserte offentlige 3Q26-estimater funnet per 19.08.2026.",
        },
        "beat_miss": _beat_miss_payload(),
        "reference_model": {
            "broker": "XP",
            "rating": "BUY",
            "target_price_brl": 31.0,
            "published_date": "2026-03-30",
            "pe_2026_reported": 11.2,
            "ev_ebitda_2026_reported": 6.6,
            "source_url": XP_MODEL_URL,
            "note": "Historisk XP-modell ved publiseringsdato; ikke løpende rekalkulert.",
        },
        "sources": [
            {"label": "Analytikerdekning og kursmål", "source": "Bemobi IR", "url": ANALYST_COVERAGE_URL},
            {"label": "Årsestimater 2026–2027", "source": "MarketScreener", "url": FORWARD_CONSENSUS_URL},
            {"label": "XP modelloppdatering", "source": "XP", "url": XP_MODEL_URL},
        ],
    }

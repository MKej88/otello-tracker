from __future__ import annotations

from datetime import date, timedelta
from typing import Any


EVENT_METADATA: dict[str, dict[str, Any]] = {
    "3Q25": {
        "result_date": "2025-11-13",
        "result_source": "Otello / Euronext",
        "result_source_url": "https://live.euronext.com/en/products/equities/company-news/2025-11-14-bemobi-3q25-reporting",
        "model_revision": {
            "status": "PUBLIC_UPDATE",
            "broker": "XP",
            "before_date": "2025-10-29",
            "after_date": "2025-11-14",
            "target_before_brl": 30.5,
            "target_after_brl": 30.5,
            "source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-revisao-do-3t25-resultados-fortes-superando-expectativas-e-acelerando-a-receita/",
            "note": "XP opprettholdt kjøpsanbefaling og kursmål R$30,5 etter 3Q25.",
            "estimate_revisions": [],
        },
    },
    "4Q25": {
        "result_date": "2026-03-19",
        "result_source": "Otello / Euronext",
        "result_source_url": "https://live.euronext.com/en/products/equities/company-news/2026-03-20-bemobi-4q25-reporting",
        "model_revision": {
            "status": "PUBLIC_UPDATE",
            "broker": "XP",
            "before_date": "2025-11-14",
            "after_date": "2026-03-30",
            "target_before_brl": 30.5,
            "target_after_brl": 31.0,
            "source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-atualizacao-do-modelo-e-comentarios-do-nosso-ndr-com-o-cfo-e-ri-da-bemobi/",
            "note": (
                "XP løftet kursmålet fra R$30,5 til R$31,0 i modelloppdateringen etter 4Q25. "
                "Oppdateringen inkluderte også konsolideringen av Paytime."
            ),
            "estimate_revisions": [
                {
                    "label": "2026E omsetningsvekst",
                    "unit": "pct",
                    "before": 14.0,
                    "after": 26.0,
                    "change_pp": 12.0,
                    "before_source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-outro-trimestre-forte/",
                    "after_source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-atualizacao-do-modelo-e-comentarios-do-nosso-ndr-com-o-cfo-e-ri-da-bemobi/",
                    "note": "Ikke en ren rapportrevisjon: den senere modellen inkluderer Paytime.",
                }
            ],
        },
    },
    "2Q26": {
        "result_date": "2026-08-11",
        "result_source": "XP resultatreview",
        "result_source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-forte-resultado-com-pagamentos-e-saas-impulsionando-o-crescimento/",
        "model_revision": {
            "status": "WAITING_FOR_PUBLIC_POST_REPORT_MODEL",
            "broker": "XP",
            "before_date": "2026-03-30",
            "after_date": None,
            "target_before_brl": 31.0,
            "target_after_brl": None,
            "source_url": "https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-forte-resultado-com-pagamentos-e-saas-impulsionando-o-crescimento/",
            "checked_date": "2026-08-20",
            "note": "2Q26-reviewen er publisert, men ingen ny offentlig XP-modell/kursmålrevisjon er verifisert ennå.",
            "estimate_revisions": [],
        },
    },
}


def _pct_change(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start == 0:
        return None
    return (end / start - 1) * 100


async def _price_rows(repository, result_date: str) -> list[dict[str, Any]]:
    target = date.fromisoformat(result_date)
    start = (target - timedelta(days=10)).isoformat()
    end = (target + timedelta(days=18)).isoformat()
    rows = await repository.all(
        """
        SELECT mp.trading_date, mp.price, mp.price_type, mp.observed_at,
               s.code AS source_code
        FROM market_prices mp
        JOIN instruments i ON i.id = mp.instrument_id
        JOIN sources s ON s.id = mp.source_id
        WHERE i.symbol = 'BMOB3'
          AND mp.trading_date BETWEEN ? AND ?
          AND mp.price_type IN ('CLOSE', 'LAST')
        ORDER BY mp.trading_date ASC,
                 CASE WHEN s.code = 'B3' THEN 0 ELSE 1 END,
                 CASE WHEN mp.price_type = 'CLOSE' THEN 0 ELSE 1 END,
                 mp.observed_at DESC
        """,
        (start, end),
    )
    best_by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        trading_date = str(row["trading_date"])
        if trading_date in best_by_date:
            continue
        try:
            price = float(row["price"])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        best_by_date[trading_date] = {
            "date": trading_date,
            "price_brl": price,
            "price_type": row.get("price_type"),
            "source": row.get("source_code"),
        }
    return [best_by_date[key] for key in sorted(best_by_date)]


async def _market_reaction(repository, result_date: str) -> dict[str, Any]:
    try:
        rows = await _price_rows(repository, result_date)
    except Exception:
        rows = []
    before = [row for row in rows if row["date"] <= result_date]
    after = [row for row in rows if row["date"] > result_date]
    if not before or not after:
        return {
            "status": "MISSING_PRICE_HISTORY",
            "result_date": result_date,
            "method": "BMOB3 sluttkurs på rapportdato mot første og femte påfølgende handelsdag.",
        }
    pre = before[-1]
    day1 = after[0]
    day5 = after[4] if len(after) >= 5 else None
    return {
        "status": "OK",
        "result_date": result_date,
        "pre": pre,
        "day1": day1,
        "day5": day5,
        "reaction_1d_pct": _pct_change(pre["price_brl"], day1["price_brl"]),
        "reaction_5d_pct": None if day5 is None else _pct_change(pre["price_brl"], day5["price_brl"]),
        "method": (
            "Resultatene ble publisert etter handel i de historiske periodene. "
            "Reaksjon måles derfor fra sluttkurs på rapportdato til første og femte påfølgende handelsdag."
        ),
    }


async def build_consensus_history(
    beat_miss: list[dict[str, Any]],
    repository,
    *,
    current_forward: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for item in beat_miss:
        period = str(item.get("period") or "")
        metadata = EVENT_METADATA.get(period)
        if metadata is None:
            continue
        result_date = str(metadata["result_date"])
        model = dict(metadata["model_revision"])
        before = model.get("target_before_brl")
        after = model.get("target_after_brl")
        model["target_revision_pct"] = _pct_change(
            float(before) if before is not None else None,
            float(after) if after is not None else None,
        )
        model["days_after_result"] = (
            (date.fromisoformat(str(model["after_date"])) - date.fromisoformat(result_date)).days
            if model.get("after_date")
            else None
        )
        events.append(
            {
                "period": period,
                "result_date": result_date,
                "result_source": metadata["result_source"],
                "result_source_url": metadata["result_source_url"],
                "expectation": {
                    "broker": item.get("broker"),
                    "published_date": item.get("published_date"),
                    "source_url": item.get("source_url"),
                    "metrics": item.get("metrics") or [],
                },
                "model_revision": model,
                "market_reaction": await _market_reaction(repository, result_date),
            }
        )
    return {
        "events": events,
        "forward_revision_tracker": {
            "source": "MarketScreener",
            "baseline_date": "2026-08-19",
            "comparison_ready": False,
            "same_source_snapshots": 1,
            "current": current_forward or [],
            "note": (
                "Samme-kilde historikk for de offentlige 2026E/2027E-aggregatene starter 19.08.2026. "
                "Neste verifiserte oppdatering kan derfor vises som en ren konsensusrevisjon uten å blande kilder."
            ),
        },
        "method_note": (
            "Kvartalsforventningene er foreløpig XP-spesifikke. Modellrevisjoner vises bare når en offentlig "
            "før/etter-observasjon kan verifiseres. Kursreaksjon beregnes fra BMOB3-prishistorikken i trackeren."
        ),
    }

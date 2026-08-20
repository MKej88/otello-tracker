from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from app.db.connection import get_connection


_TRACKED_FORWARD_METRICS = (
    ("revenue_mbrl", "Omsetning"),
    ("ebitda_mbrl", "EBITDA"),
    ("ebit_mbrl", "EBIT"),
    ("net_income_mbrl", "Resultat"),
    ("eps_brl", "EPS"),
    ("net_debt_mbrl", "Netto gjeld"),
)


def _pct_change(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start == 0:
        return None
    return (end / start - 1) * 100


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _event_metadata(database_path: str | None) -> dict[str, dict[str, Any]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT period, result_date, result_source, result_source_url,
                   model_revision_json, quality, notes
            FROM bemobi_consensus_events
            ORDER BY result_date, id
            """
        ).fetchall()
    return {
        str(row["period"]): {
            "result_date": str(row["result_date"]),
            "result_source": row["result_source"],
            "result_source_url": row["result_source_url"],
            "model_revision": _json_object(row["model_revision_json"]),
            "quality": row["quality"],
            "notes": row["notes"],
        }
        for row in rows
    }


def _forward_snapshots(database_path: str | None) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT source_name, observed_date, payload_json, content_hash,
                   source_url, quality
            FROM bemobi_forward_consensus_snapshots
            ORDER BY observed_date, id
            """
        ).fetchall()
    snapshots: list[dict[str, Any]] = []
    for row in rows:
        payload = _json_object(row["payload_json"])
        years = payload.get("years")
        if not isinstance(years, list):
            continue
        snapshots.append(
            {
                "source": row["source_name"],
                "date": row["observed_date"],
                "years": years,
                "content_hash": row["content_hash"],
                "source_url": row["source_url"],
                "quality": row["quality"],
            }
        )
    return snapshots


def _snapshot_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    before_years = {
        int(item["year"]): item
        for item in before.get("years") or []
        if isinstance(item, dict) and item.get("year") is not None
    }
    after_years = {
        int(item["year"]): item
        for item in after.get("years") or []
        if isinstance(item, dict) and item.get("year") is not None
    }
    changes: list[dict[str, Any]] = []
    for year in sorted(set(before_years) & set(after_years)):
        old = before_years[year]
        new = after_years[year]
        for metric, label in _TRACKED_FORWARD_METRICS:
            try:
                old_value = float(old[metric])
                new_value = float(new[metric])
            except (KeyError, TypeError, ValueError):
                continue
            if abs(new_value - old_value) < 1e-12:
                continue
            changes.append(
                {
                    "year": year,
                    "metric": metric,
                    "label": label,
                    "before": old_value,
                    "after": new_value,
                    "change": new_value - old_value,
                    "change_pct": _pct_change(old_value, new_value),
                }
            )
    return changes


def _forward_tracker(
    database_path: str | None,
    current_forward: list[dict[str, Any]],
) -> dict[str, Any]:
    snapshots = _forward_snapshots(database_path)
    if not snapshots:
        return {
            "source": "MarketScreener",
            "baseline_date": None,
            "latest_date": None,
            "comparison_ready": False,
            "same_source_snapshots": 0,
            "latest_changes": [],
            "current": current_forward,
            "note": "Ingen kildebevarte MarketScreener-snapshots er registrert ennå.",
        }

    latest = snapshots[-1]
    previous = snapshots[-2] if len(snapshots) >= 2 else None
    changes = _snapshot_changes(previous, latest) if previous is not None else []
    return {
        "source": latest.get("source") or "MarketScreener",
        "baseline_date": snapshots[0]["date"],
        "latest_date": latest["date"],
        "comparison_ready": previous is not None,
        "same_source_snapshots": len(snapshots),
        "latest_changes": changes,
        "current": current_forward,
        "note": (
            "Hver vellykket offentlig MarketScreener-observasjon lagres append-only. "
            "Sammenligningen bruker de to siste samme-kilde-snapshotene og blander ikke meglerhus."
        ),
    }


def _price_rows(database_path: str | None, result_date: str) -> list[dict[str, Any]]:
    target = date.fromisoformat(result_date)
    start = (target - timedelta(days=10)).isoformat()
    end = (target + timedelta(days=18)).isoformat()
    try:
        with get_connection(database_path) as connection:
            rows = connection.execute(
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
            ).fetchall()
    except Exception:
        return []

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
            "price_type": row["price_type"],
            "source": row["source_code"],
        }
    return [best_by_date[key] for key in sorted(best_by_date)]


def _market_reaction(database_path: str | None, result_date: str) -> dict[str, Any]:
    rows = _price_rows(database_path, result_date)
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


def _target_revision(model: dict[str, Any], result_date: str) -> dict[str, Any]:
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
    return model


def build_consensus_history(
    beat_miss: list[dict[str, Any]],
    database_path: str | None,
    *,
    current_forward: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata_by_period = _event_metadata(database_path)
    events: list[dict[str, Any]] = []
    for item in beat_miss:
        period = str(item.get("period") or "")
        metadata = metadata_by_period.get(period)
        if metadata is None:
            continue
        result_date = str(metadata["result_date"])
        model = _target_revision(dict(metadata["model_revision"]), result_date)
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
                "market_reaction": _market_reaction(database_path, result_date),
            }
        )

    return {
        "events": events,
        "forward_revision_tracker": _forward_tracker(database_path, current_forward or []),
        "method_note": (
            "Historiske rapport-/modellhendelser ligger i databasen, ikke i Python-kode. "
            "Kvartalsforventningene er foreløpig XP-spesifikke; MarketScreener-revisjoner "
            "sammenlignes kun mot tidligere snapshot fra samme kilde."
        ),
    }

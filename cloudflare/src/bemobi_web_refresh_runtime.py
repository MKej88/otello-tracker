"""Aktiv Bemobi web-orkestrering for Cloudflare Full Workflow.

Modulen bygger på parser- og kildehjelperne i ``bemobi_web_refresh`` og eier den
rullerende forward-konsensusen, append-only snapshots og consensus-history-eventer.
Det separate modulnavnet gjør runtime-ansvaret eksplisitt uten et tidsavhengig ``v2``-navn.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Awaitable, Callable

from bemobi_web_refresh import (
    MARKETSCREENER_FINANCES_URL,
    MAX_HTML_BYTES,
    _decode_html,
    _fetch_bytes,
    _html_parser,
    _metric_key,
    _number,
    _store_web_document,
    _upsert_fact,
    sync_bemobi_ir,
    sync_latest_result_release,
    sync_xp_preview,
)


_REQUIRED_FORWARD_METRICS = {
    "revenue_mbrl",
    "ebitda_mbrl",
    "ebit_mbrl",
    "net_income_mbrl",
    "eps_brl",
    "net_debt_mbrl",
}


def parse_forward_consensus_html(
    html: str,
    *,
    as_of_year: int,
    forward_years: int = 2,
) -> list[dict[str, Any]]:
    """Parse the next complete MarketScreener forecast years without calendar hardcoding."""
    rows = _html_parser(html).rows
    year_positions: dict[int, int] = {}
    for row in rows:
        positions = {
            int(cell): idx
            for idx, cell in enumerate(row)
            if re.fullmatch(r"20\d{2}", str(cell).strip()) and 2000 <= int(cell) <= 2100
        }
        if len(positions) >= 2:
            year_positions = positions
            break
    if not year_positions:
        raise ValueError("MarketScreener årskolonner ikke funnet")

    metrics: dict[str, dict[int, float]] = {}
    for row in rows:
        if not row:
            continue
        key = _metric_key(row[0])
        if key is None:
            continue
        for year, idx in year_positions.items():
            if idx >= len(row):
                continue
            try:
                value = _number(row[idx], million_scale=key != "eps_brl")
            except ValueError:
                continue
            metrics.setdefault(key, {})[year] = value

    complete_years = [
        year
        for year in sorted(year_positions)
        if year >= as_of_year
        and all(year in metrics.get(metric, {}) for metric in _REQUIRED_FORWARD_METRICS)
    ]
    selected = complete_years[:forward_years]
    if len(selected) < forward_years:
        raise ValueError(
            f"MarketScreener har bare {len(selected)} komplette forward-år fra {as_of_year}"
        )

    result: list[dict[str, Any]] = []
    for year in selected:
        payload = {
            "year": year,
            **{metric: metrics[metric][year] for metric in _REQUIRED_FORWARD_METRICS},
        }
        if not (
            0 < payload["revenue_mbrl"] < 10_000
            and 0 < payload["ebitda_mbrl"] < payload["revenue_mbrl"]
        ):
            raise ValueError(f"MarketScreener {year} har ulogiske estimater")
        if not (
            -5_000 < payload["net_debt_mbrl"] < 5_000
            and 0 < payload["eps_brl"] < 100
        ):
            raise ValueError(f"MarketScreener {year} har estimater utenfor kontrollgrenser")
        result.append(payload)
    return result


def _snapshot_payload(years: list[dict[str, Any]]) -> tuple[str, str]:
    payload = json.dumps(
        {"years": years},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _store_forward_snapshot(
    repository,
    *,
    target_date: str,
    years: list[dict[str, Any]],
    source_document_id: int,
) -> int:
    payload_json, content_hash = _snapshot_payload(years)
    existing = await repository.first(
        """
        SELECT id FROM bemobi_forward_consensus_snapshots
        WHERE source_name='MarketScreener' AND observed_date=? AND content_hash=?
        LIMIT 1
        """,
        (target_date, content_hash),
    )
    if existing is not None:
        return 0
    await repository.run(
        """
        INSERT INTO bemobi_forward_consensus_snapshots(
            source_name, observed_date, payload_json, content_hash,
            source_url, source_document_id, quality
        ) VALUES ('MarketScreener', ?, ?, ?, ?, ?, 'PUBLIC_AGGREGATE_AUTO')
        """,
        (
            target_date,
            payload_json,
            content_hash,
            MARKETSCREENER_FINANCES_URL,
            source_document_id,
        ),
    )
    return 1


async def _ensure_consensus_event(
    repository,
    *,
    result_refresh: dict[str, Any],
    target_date: str,
) -> int:
    """Create a data-backed history shell for a newly ingested result, without inventing broker data."""
    if result_refresh.get("status") != "ok" or not result_refresh.get("period"):
        return 0
    period = str(result_refresh["period"])
    existing = await repository.first(
        "SELECT id FROM bemobi_consensus_events WHERE period=? LIMIT 1",
        (period,),
    )
    if existing is not None:
        return 0

    fact = await repository.first(
        """
        SELECT published_date, source_name, source_url, source_document_id
        FROM bemobi_investor_facts
        WHERE fact_type='RESULT' AND fact_key=?
        LIMIT 1
        """,
        (period,),
    )
    if fact is None or not fact.get("published_date"):
        return 0

    model_revision = {
        "status": "WAITING_FOR_PUBLIC_POST_REPORT_MODEL",
        "broker": "XP",
        "before_date": None,
        "after_date": None,
        "target_before_brl": None,
        "target_after_brl": None,
        "source_url": fact.get("source_url"),
        "checked_date": target_date,
        "note": (
            "Ny rapport er registrert. Trackeren venter på en kildeverifisert offentlig "
            "etterrapport-modell før kursmål eller estimatrevisjon fylles inn."
        ),
        "estimate_revisions": [],
    }
    await repository.run(
        """
        INSERT INTO bemobi_consensus_events(
            period, result_date, result_source, result_source_url,
            model_revision_json, quality, notes, source_document_id
        ) VALUES (?, ?, ?, ?, ?, 'AUTO_RESULT_HISTORY', ?, ?)
        """,
        (
            period,
            str(fact["published_date"])[:10],
            str(fact.get("source_name") or "Bemobi/CVM"),
            fact.get("source_url"),
            json.dumps(
                model_revision,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "Opprettet automatisk fra kildebelagt RESULT-faktum; brokerrevisjon fylles ikke uten kilde.",
            fact.get("source_document_id"),
        ),
    )
    return 1


async def sync_marketscreener_consensus(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    try:
        raw = await _fetch_bytes(
            MARKETSCREENER_FINANCES_URL,
            label="MarketScreener Bemobi finances",
            max_bytes=MAX_HTML_BYTES,
            fetcher=fetcher,
        )
        target_year = date.fromisoformat(target_date).year
        years = parse_forward_consensus_html(
            _decode_html(raw),
            as_of_year=target_year,
        )
    except Exception as exc:
        return {"status": "not_available", "error": str(exc)[:700], "rows_written": 0}

    document_id = await _store_web_document(
        repository,
        archive_bucket,
        source_code="MARKETSCREENER",
        url=MARKETSCREENER_FINANCES_URL,
        kind="forward-consensus",
        title="Bemobi MarketScreener finances",
        target_date=target_date,
        payload=raw,
    )
    snapshot_rows = await _store_forward_snapshot(
        repository,
        target_date=target_date,
        years=years,
        source_document_id=document_id,
    )

    for item in years:
        await _upsert_fact(
            repository,
            fact_type="FORWARD_CONSENSUS",
            fact_key=str(item["year"]),
            as_of_date=target_date,
            published_date=None,
            payload=item,
            source_name="MarketScreener",
            source_url=MARKETSCREENER_FINANCES_URL,
            source_document_id=document_id,
            quality="PUBLIC_AGGREGATE_AUTO",
            notes=(
                "Automatisk hentet offentlig aggregert konsensus; siste gode data beholdes "
                "ved kildefeil og hver vellykket observasjon snapshots separat."
            ),
        )

    keys = [str(item["year"]) for item in years]
    placeholders = ",".join("?" for _ in keys)
    await repository.run(
        f"DELETE FROM bemobi_investor_facts "
        f"WHERE fact_type='FORWARD_CONSENSUS' AND fact_key NOT IN ({placeholders})",
        tuple(keys),
    )
    return {
        "status": "ok",
        "years": [item["year"] for item in years],
        "rows_written": len(years) + snapshot_rows,
        "fact_rows_written": len(years),
        "snapshot_rows_written": snapshot_rows,
        "snapshot_policy": "append-only-same-source",
    }


async def refresh_bemobi_web(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh Bemobi facts with dynamic forward years and append-only consensus history."""
    ir = await sync_bemobi_ir(
        repository,
        target_date=target_date,
        archive_bucket=archive_bucket,
        fetcher=fetcher,
    )
    result = await sync_latest_result_release(
        repository,
        target_date=target_date,
        archive_bucket=archive_bucket,
        fetcher=fetcher,
    )
    event_rows = await _ensure_consensus_event(
        repository,
        result_refresh=result,
        target_date=target_date,
    )
    if event_rows:
        result = {**result, "consensus_event_rows_written": event_rows}
    consensus = await sync_marketscreener_consensus(
        repository,
        target_date=target_date,
        archive_bucket=archive_bucket,
        fetcher=fetcher,
    )
    xp = await sync_xp_preview(
        repository,
        target_date=target_date,
        archive_bucket=archive_bucket,
        fetcher=fetcher,
    )
    secondary = [result, consensus, xp]
    degraded = any(item.get("status") == "not_available" for item in secondary)
    rows_written = sum(int(item.get("rows_written") or 0) for item in [ir, *secondary]) + event_rows
    return {
        "status": "partial" if degraded else "ok",
        "rows_written": rows_written,
        "ir": ir,
        "result_release": result,
        "consensus": consensus,
        "xp_preview": xp,
        "policy": "official-first-last-good-preserved",
    }

"""Bemobi IR refresh split into ownership-critical and analyst best-effort domains."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from bemobi_web_refresh import (
    BEMOBI_ANALYST_URL,
    BEMOBI_OWNERSHIP_URL,
    MAX_HTML_BYTES,
    _analyst_prune_decision,
    _decode_html,
    _fetch_bytes,
    _store_web_document,
    _sync_holding,
    _upsert_fact,
    parse_analyst_coverage_html,
    parse_ownership_html,
)


async def _previous_ir_analyst_keys(repository) -> set[str] | None:
    """Read the last successful analyst observation, with legacy metadata fallback."""
    row = await repository.first(
        """
        SELECT sh.metadata_json
        FROM source_health sh
        JOIN sources s ON s.id=sh.source_id
        WHERE s.code='BEMOBI_IR'
        ORDER BY sh.checked_at DESC, sh.id DESC
        LIMIT 1
        """
    )
    if row is None:
        return None
    try:
        metadata = json.loads(str(row.get("metadata_json") or "{}"))
        ir = (metadata.get("result") or {}).get("ir") or {}
        analyst = ir.get("analyst_coverage")
        if isinstance(analyst, dict):
            if analyst.get("status") != "ok":
                return None
            keys = analyst.get("analyst_keys")
        else:
            # Compatibility with source-health rows written before the failure-domain split.
            keys = ir.get("analyst_keys")
        if not isinstance(keys, list):
            return None
        return {str(item) for item in keys if str(item)}
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


async def sync_bemobi_ownership(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh ownership and the Otello holding from Bemobi's official IR page."""
    ownership_raw = await _fetch_bytes(
        BEMOBI_OWNERSHIP_URL,
        label="Bemobi IR ownership",
        max_bytes=MAX_HTML_BYTES,
        fetcher=fetcher,
    )
    ownership = parse_ownership_html(_decode_html(ownership_raw), checked_date=target_date)
    ownership_doc = await _store_web_document(
        repository,
        archive_bucket,
        source_code="BEMOBI_IR",
        url=BEMOBI_OWNERSHIP_URL,
        kind="ownership",
        title="Bemobi ownership structure",
        target_date=target_date,
        payload=ownership_raw,
    )
    await _upsert_fact(
        repository,
        fact_type="OWNERSHIP",
        fact_key="current",
        as_of_date=target_date,
        published_date=None,
        payload=ownership,
        source_name="Bemobi IR",
        source_url=BEMOBI_OWNERSHIP_URL,
        source_document_id=ownership_doc,
        quality="OFFICIAL_IR_AUTO",
        notes="Automatisk kontrollert mot Bemobis offisielle aksjonærside.",
    )
    holding_changes = await _sync_holding(
        repository,
        ownership,
        ownership_doc,
        target_date,
    )
    return {
        "status": "ok",
        "ownership": ownership,
        "holding_changes": holding_changes,
        "rows_written": 1 + holding_changes,
    }


async def sync_bemobi_analyst_coverage(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh analyst coverage without owning the health of core Bemobi IR data."""
    analyst_raw = await _fetch_bytes(
        BEMOBI_ANALYST_URL,
        label="Bemobi IR analyst coverage",
        max_bytes=MAX_HTML_BYTES,
        fetcher=fetcher,
    )
    analysts = parse_analyst_coverage_html(_decode_html(analyst_raw))
    analyst_doc = await _store_web_document(
        repository,
        archive_bucket,
        source_code="BEMOBI_IR",
        url=BEMOBI_ANALYST_URL,
        kind="analyst-coverage",
        title="Bemobi analyst coverage",
        target_date=target_date,
        payload=analyst_raw,
    )

    names = [item["institution"] for item in analysts]
    observed_keys = set(names)
    existing_rows = await repository.all(
        "SELECT fact_key FROM bemobi_investor_facts WHERE fact_type='ANALYST' ORDER BY fact_key"
    )
    existing_keys = {str(row["fact_key"]) for row in existing_rows}
    previous_observed_keys = await _previous_ir_analyst_keys(repository)
    allow_prune, missing_keys = _analyst_prune_decision(
        existing_keys,
        observed_keys,
        previous_observed_keys,
    )

    # Upsert first. If a later write fails, stale analyst facts remain instead of being
    # destructively pruned before the new observation has been persisted.
    for analyst in analysts:
        await _upsert_fact(
            repository,
            fact_type="ANALYST",
            fact_key=analyst["institution"],
            as_of_date=target_date,
            published_date=analyst["last_update"],
            payload=analyst,
            source_name="Bemobi IR",
            source_url=BEMOBI_ANALYST_URL,
            source_document_id=analyst_doc,
            quality="OFFICIAL_IR_AUTO",
            notes="Automatisk hentet fra Bemobi IR analytikerdekning.",
        )

    pruned: list[str] = []
    deferred: list[str] = []
    if missing_keys and allow_prune:
        placeholders = ",".join("?" for _ in names)
        await repository.run(
            f"DELETE FROM bemobi_investor_facts WHERE fact_type='ANALYST' AND fact_key NOT IN ({placeholders})",
            tuple(names),
        )
        pruned = missing_keys
    elif missing_keys:
        deferred = missing_keys

    return {
        "status": "ok",
        "analyst_count": len(analysts),
        "analyst_keys": sorted(observed_keys),
        "analyst_pruned": pruned,
        "analyst_prune_deferred": deferred,
        "rows_written": len(analysts),
    }


async def sync_bemobi_ir(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh core ownership first and keep analyst coverage explicitly best-effort."""
    ownership_refresh = await sync_bemobi_ownership(
        repository,
        target_date=target_date,
        archive_bucket=archive_bucket,
        fetcher=fetcher,
    )

    try:
        analyst_coverage = await sync_bemobi_analyst_coverage(
            repository,
            target_date=target_date,
            archive_bucket=archive_bucket,
            fetcher=fetcher,
        )
    except Exception as exc:
        analyst_coverage = {
            "status": "not_available",
            "reason": "analyst_coverage_refresh_failed",
            "error": str(exc)[:700],
            "error_type": type(exc).__name__,
            "failed_url": BEMOBI_ANALYST_URL,
            "last_good_preserved": True,
            "rows_written": 0,
        }

    result: dict[str, Any] = {
        "status": "ok",
        "ownership": ownership_refresh["ownership"],
        "ownership_refresh": ownership_refresh,
        "analyst_coverage": analyst_coverage,
        "holding_changes": int(ownership_refresh.get("holding_changes") or 0),
        "rows_written": (
            int(ownership_refresh.get("rows_written") or 0)
            + int(analyst_coverage.get("rows_written") or 0)
        ),
    }

    # Preserve the old successful-result shape for existing diagnostics and consumers.
    if analyst_coverage.get("status") == "ok":
        for key in (
            "analyst_count",
            "analyst_keys",
            "analyst_pruned",
            "analyst_prune_deferred",
        ):
            result[key] = analyst_coverage.get(key)

    return result

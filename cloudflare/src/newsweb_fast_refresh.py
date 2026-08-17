from __future__ import annotations

import json
from collections import Counter
from typing import Any, Awaitable, Callable

try:
    from .newsweb_buybacks import (
        BUYBACK_TITLE,
        _NO_PURCHASE_RE,
        _store_no_purchase_message,
        buyback_start_for_refresh,
        ingest_weekly_buyback,
        normalize_weekly_body,
        parse_newsweb_weekly_status,
    )
    from .newsweb_client import NewsWebMessage, discover_otec_messages, fetch_message
    from .newsweb_ingestion import archive_message, history_start_for_refresh
except ImportError:
    from newsweb_buybacks import (
        BUYBACK_TITLE,
        _NO_PURCHASE_RE,
        _store_no_purchase_message,
        buyback_start_for_refresh,
        ingest_weekly_buyback,
        normalize_weekly_body,
        parse_newsweb_weekly_status,
    )
    from newsweb_client import NewsWebMessage, discover_otec_messages, fetch_message
    from newsweb_ingestion import archive_message, history_start_for_refresh


def _error(item: NewsWebMessage, exc: Exception) -> dict[str, Any]:
    return {
        "message_id": item.message_id,
        "published_at": item.published_at,
        "title": item.title,
        "error": str(exc)[:1000],
    }


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


async def _existing_newsweb_documents(repository) -> dict[str, dict[str, Any]]:
    """Load the small NewsWeb provenance index once for the entire fast refresh."""
    rows = await repository.all(
        """
        SELECT sd.external_id, sd.metadata_json
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='NEWSWEB' AND sd.external_id IS NOT NULL
        """
    )
    return {
        str(row["external_id"]): _metadata(row.get("metadata_json"))
        for row in rows
        if row.get("external_id")
    }


def _buyback_already_processed(
    existing: dict[str, dict[str, Any]],
    message: NewsWebMessage,
) -> bool:
    if message.public_url in existing:
        return True
    archive_meta = existing.get(f"newsweb-message:{message.message_id}") or {}
    return archive_meta.get("buyback_status") == "NO_PURCHASES"


async def collect_newsweb_fast(
    repository,
    *,
    to_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Discover once, fetch each new message once, then fan out to both parsers.

    The fast path deliberately trusts NewsWeb correction message IDs. A heavier full-refresh
    reconciliation can revalidate historical content hashes without making every 30-minute
    cycle refetch the same message bodies.
    """
    history_start = await history_start_for_refresh(repository)
    buyback_start = await buyback_start_for_refresh(repository)
    combined_start = min(history_start, buyback_start)

    discovered = await discover_otec_messages(combined_start, to_date, fetcher=fetcher)
    existing = await _existing_newsweb_documents(repository)

    history_results: list[dict[str, Any]] = []
    history_errors: list[dict[str, Any]] = []
    buyback_results: list[dict[str, Any]] = []
    buyback_errors: list[dict[str, Any]] = []
    full_messages_fetched = 0
    skipped_existing = 0
    history_in_scope = 0
    buybacks_in_scope = 0

    for item in discovered:
        item_date = str(item.published_at)[:10]
        history_scope = item_date >= history_start
        buyback_scope = item_date >= buyback_start and BUYBACK_TITLE in item.title.lower()
        if history_scope:
            history_in_scope += 1
        if buyback_scope:
            buybacks_in_scope += 1

        archive_external_id = f"newsweb-message:{item.message_id}"
        needs_history = history_scope and archive_external_id not in existing
        needs_buyback = buyback_scope and not _buyback_already_processed(existing, item)
        if not needs_history and not needs_buyback:
            skipped_existing += 1
            continue

        try:
            message = await fetch_message(item.message_id, fetcher=fetcher)
            full_messages_fetched += 1
        except Exception as exc:
            if needs_history:
                history_errors.append(_error(item, exc))
            if needs_buyback:
                buyback_errors.append(_error(item, exc))
            continue

        if needs_history:
            try:
                archived = await archive_message(repository, message)
                history_results.append(archived)
                existing[archive_external_id] = {}
            except Exception as exc:
                history_errors.append(_error(item, exc))

        if needs_buyback:
            try:
                if BUYBACK_TITLE not in message.title.lower():
                    raise ValueError(
                        f"NewsWeb-melding {message.message_id} er ikke en buyback-status"
                    )
                clean = normalize_weekly_body(message.body)
                no_purchase = _NO_PURCHASE_RE.search(clean)
                if no_purchase:
                    document_id = await _store_no_purchase_message(
                        repository,
                        message,
                        no_purchase.group(0),
                    )
                    result = {
                        "message_id": message.message_id,
                        "canonical_source_document_id": document_id,
                        "daily_rows_written": 0,
                        "daily_rows": 0,
                        "daily_status": "NO_PURCHASES",
                        "attachment_status": (
                            "DEFERRED_TO_FULL_REFRESH_R2"
                            if message.attachments
                            else "NO_ATTACHMENT"
                        ),
                    }
                    existing[archive_external_id] = {"buyback_status": "NO_PURCHASES"}
                else:
                    parsed = parse_newsweb_weekly_status(clean)
                    result = await ingest_weekly_buyback(repository, message, parsed)
                    existing[message.public_url] = {}
                buyback_results.append(result)
            except Exception as exc:
                buyback_errors.append(_error(item, exc))

    history_categories = Counter(item["category"] for item in history_results)
    history_status = (
        "error"
        if history_errors and not history_results
        else ("partial" if history_errors else "ok")
    )
    buyback_status = (
        "error"
        if buyback_errors and not buyback_results
        else ("partial" if buyback_errors else "ok")
    )

    history = {
        "status": history_status,
        "from": history_start,
        "to": to_date,
        "discovered": history_in_scope,
        "archived": len(history_results),
        "errors": history_errors,
        "requires_review": sum(1 for item in history_results if item["requires_review"]),
        "categories": dict(sorted(history_categories.items())),
    }
    buybacks = {
        "status": buyback_status,
        "source": "Oslo Børs NewsWeb",
        "issuer_id": 7759,
        "from": buyback_start,
        "to": to_date,
        "discovered": buybacks_in_scope,
        "ingested": len(buyback_results),
        "no_purchase_count": sum(
            item.get("daily_status") == "NO_PURCHASES" for item in buyback_results
        ),
        "attachments_deferred": sum(
            item.get("attachment_status") == "DEFERRED_TO_FULL_REFRESH_R2"
            for item in buyback_results
        ),
        "results": buyback_results,
        "errors": buyback_errors,
    }
    return {
        "status": (
            "error"
            if history_status == "error" and buyback_status == "error"
            else (
                "partial"
                if history_status in {"error", "partial"}
                or buyback_status in {"error", "partial"}
                else "ok"
            )
        ),
        "from": combined_start,
        "to": to_date,
        "discovered": len(discovered),
        "full_messages_fetched": full_messages_fetched,
        "skipped_existing": skipped_existing,
        "reconciliation_policy": "FAST_ID_DEDUPE_FULL_HASH_REVALIDATION_DEFERRED",
        "history": history,
        "buybacks": buybacks,
    }

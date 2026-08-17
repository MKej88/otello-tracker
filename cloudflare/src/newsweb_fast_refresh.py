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
        SELECT sd.external_id, sd.metadata_json, sd.fetched_at
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='NEWSWEB' AND sd.external_id IS NOT NULL
        """
    )
    return {
        str(row["external_id"]): {
            **_metadata(row.get("metadata_json")),
            "_fetched_at": row.get("fetched_at"),
        }
        for row in rows
        if row.get("external_id")
    }


def _revalidation_due(
    existing: dict[str, dict[str, Any]],
    external_id: str,
    to_date: str,
) -> bool:
    """Revalidate stable NewsWeb IDs at most once per calendar day.

    This keeps the immutable-content guarantee from 15.4.6: if NewsWeb mutates a body
    under a stable ID, the changed hash is still discovered. It avoids doing the same
    full-message fetch on every 30-minute cron invocation.
    """
    item = existing.get(external_id)
    if item is None:
        return False
    fetched_date = str(item.get("_fetched_at") or "")[:10]
    return not fetched_date or fetched_date < to_date


def _buyback_processed_key(
    existing: dict[str, dict[str, Any]],
    message: NewsWebMessage,
) -> str | None:
    if message.public_url in existing:
        return message.public_url
    archive_external_id = f"newsweb-message:{message.message_id}"
    archive_meta = existing.get(archive_external_id) or {}
    if archive_meta.get("buyback_status") == "NO_PURCHASES":
        return archive_external_id
    return None


async def collect_newsweb_fast(
    repository,
    *,
    to_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Discover once, fetch each needed message once, then fan out to both parsers.

    Existing messages are normally skipped. During the first cron invocation of a new
    calendar day, recent overlap-window messages are hash-revalidated once so a provider
    body mutation under a stable ID is still detected without 30-minute refetch churn.
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
    daily_revalidations = 0
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
        archive_exists = archive_external_id in existing
        history_revalidation = (
            history_scope
            and archive_exists
            and _revalidation_due(existing, archive_external_id, to_date)
        )
        needs_history = history_scope and (not archive_exists or history_revalidation)

        buyback_key = _buyback_processed_key(existing, item) if buyback_scope else None
        buyback_revalidation = (
            buyback_scope
            and buyback_key is not None
            and _revalidation_due(existing, buyback_key, to_date)
        )
        needs_buyback = buyback_scope and (buyback_key is None or buyback_revalidation)

        if not needs_history and not needs_buyback:
            skipped_existing += 1
            continue
        if history_revalidation or buyback_revalidation:
            daily_revalidations += 1

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
                existing[archive_external_id] = {"_fetched_at": f"{to_date}T00:00:00Z"}
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
                    existing[archive_external_id] = {
                        "buyback_status": "NO_PURCHASES",
                        "_fetched_at": f"{to_date}T00:00:00Z",
                    }
                else:
                    parsed = parse_newsweb_weekly_status(clean)
                    result = await ingest_weekly_buyback(repository, message, parsed)
                    existing[message.public_url] = {"_fetched_at": f"{to_date}T00:00:00Z"}
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
        "daily_revalidations": daily_revalidations,
        "reconciliation_policy": "FAST_ID_DEDUPE_DAILY_HASH_REVALIDATION",
        "history": history,
        "buybacks": buybacks,
    }

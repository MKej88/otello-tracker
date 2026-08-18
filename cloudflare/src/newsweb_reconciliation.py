from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Awaitable, Callable

try:
    from .newsweb_buybacks import collect_newsweb_buybacks
    from .newsweb_ingestion import collect_newsweb_history
except ImportError:
    from newsweb_buybacks import collect_newsweb_buybacks
    from newsweb_ingestion import collect_newsweb_history

RECONCILIATION_LOOKBACK_DAYS = 45


async def reconcile_newsweb(
    repository,
    *,
    target_date: str,
    lookback_days: int = RECONCILIATION_LOOKBACK_DAYS,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Re-fetch the overlap window and revalidate body hashes plus buyback facts.

    The 30-minute fast path intentionally deduplicates already-seen message IDs. This
    durable pass is the stronger correction/reconciliation layer: every recent official
    message is fetched again, so changed content under a stable NewsWeb ID is captured by
    the immutable source-document versioning introduced in Phase 15.4.6.
    """
    target = date.fromisoformat(target_date)
    start = (target - timedelta(days=max(21, lookback_days))).isoformat()

    history = await collect_newsweb_history(
        repository,
        from_date=start,
        to_date=target_date,
        fetcher=fetcher,
    )
    buybacks = await collect_newsweb_buybacks(
        repository,
        from_date=start,
        to_date=target_date,
        fetcher=fetcher,
    )

    errors: list[dict[str, Any]] = []
    for scope, result in (("history", history), ("buybacks", buybacks)):
        for item in result.get("errors") or []:
            errors.append({"scope": scope, **item})

    if history.get("status") == "error" and buybacks.get("status") == "error":
        status = "error"
    elif errors or history.get("status") == "partial" or buybacks.get("status") == "partial":
        status = "partial"
    else:
        status = "ok"

    return {
        "status": status,
        "from": start,
        "to": target_date,
        "reconciliation_policy": "FULL_OVERLAP_BODY_HASH_REVALIDATION",
        "history": history,
        "buybacks": buybacks,
        "errors": errors,
    }

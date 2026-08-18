from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

try:
    from .newsweb_daily_buybacks import PARSER_VERSION, enrich_newsweb_buybacks_with_r2
except ImportError:
    from newsweb_daily_buybacks import PARSER_VERSION, enrich_newsweb_buybacks_with_r2

PDF_REVALIDATION_DAYS = 30
RECENT_ATTACHMENT_ROWS = 25


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


async def _latest_current_parser_attachment(repository) -> dict[str, Any] | None:
    rows = await repository.all(
        """
        SELECT sd.id, sd.fetched_at, sd.content_sha256, sd.metadata_json
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='NEWSWEB'
          AND sd.document_type='BUYBACK_TRANSACTION_ATTACHMENT'
        ORDER BY sd.fetched_at DESC, sd.id DESC
        LIMIT ?
        """,
        (RECENT_ATTACHMENT_ROWS,),
    )
    for row in rows:
        metadata = _metadata(row.get("metadata_json"))
        if metadata.get("parser") != PARSER_VERSION:
            continue
        reconciliation = metadata.get("weekly_reconciliation") or {}
        if reconciliation.get("quality") not in {"CONFIRMED", "RECONCILED"}:
            continue
        return {**row, "metadata": metadata}
    return None


async def _coverage_state(repository) -> dict[str, Any]:
    row = await repository.first(
        """
        SELECT
          (SELECT MAX(trade_date) FROM buybacks) AS latest_weekly_date,
          (SELECT MAX(trade_date) FROM buyback_daily_transactions) AS latest_daily_date
        """
    ) or {}
    attachment = await _latest_current_parser_attachment(repository)
    return {
        "latest_weekly_date": row.get("latest_weekly_date"),
        "latest_daily_date": row.get("latest_daily_date"),
        "attachment": attachment,
    }


def _revalidation_due(attachment: dict[str, Any] | None, target_date: str) -> bool:
    if attachment is None:
        return True
    fetched = str(attachment.get("fetched_at") or "")[:10]
    if not fetched:
        return True
    try:
        fetched_day = date.fromisoformat(fetched)
        target = date.fromisoformat(target_date)
    except ValueError:
        return True
    return target - fetched_day >= timedelta(days=PDF_REVALIDATION_DAYS)


async def enrich_newsweb_buybacks_if_due(
    repository,
    bucket,
    *,
    target_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Run expensive PDF reconciliation only for new coverage or periodic revalidation."""
    state = await _coverage_state(repository)
    weekly = str(state.get("latest_weekly_date") or "")
    daily = str(state.get("latest_daily_date") or "")
    attachment = state.get("attachment")

    new_weekly_coverage = bool(weekly and (not daily or weekly > daily))
    revalidation_due = _revalidation_due(attachment, target_date)
    if not new_weekly_coverage and not revalidation_due:
        metadata = (attachment or {}).get("metadata") or {}
        return {
            "status": "ok",
            "skipped": True,
            "reason": "pdf_coverage_current",
            "parser": PARSER_VERSION,
            "pdf_revalidation_days": PDF_REVALIDATION_DAYS,
            "latest_weekly_date": weekly or None,
            "latest_daily_date": daily or None,
            "last_attachment_fetched_at": (attachment or {}).get("fetched_at"),
            "last_attachment_sha256": (attachment or {}).get("content_sha256"),
            "last_attachment_r2_key": metadata.get("r2_key"),
            "pdfs_archived": 0,
            "daily_rows": 0,
            "daily_rows_written": 0,
            "cash_weeks_synced": 0,
        }

    result = await enrich_newsweb_buybacks_with_r2(
        repository,
        bucket,
        target_date=target_date,
        fetcher=fetcher,
    )
    return {
        **result,
        "skipped": False,
        "refresh_reason": "new_weekly_coverage" if new_weekly_coverage else "periodic_hash_revalidation",
        "pdf_revalidation_days": PDF_REVALIDATION_DAYS,
    }

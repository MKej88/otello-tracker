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
_COMPLETED_WEEKLY_KEY = f"newsweb_pdf_refresh_completed_weekly:{PARSER_VERSION}"
_LAST_SUCCESS_KEY = f"newsweb_pdf_refresh_last_success:{PARSER_VERSION}"


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _weekly_fingerprint(row: dict[str, Any] | None) -> str | None:
    if not row or row.get("weekly_id") is None:
        return None
    return json.dumps(
        {
            "id": int(row["weekly_id"]),
            "trade_date": str(row.get("latest_weekly_date") or ""),
            "source_document_id": int(row.get("weekly_source_document_id") or 0),
            "shares": int(row.get("weekly_shares") or 0),
            "amount_nok": str(row.get("weekly_amount_nok") or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


async def _runtime_value(repository, key: str) -> str | None:
    row = await repository.first("SELECT value FROM runtime_state WHERE key=? LIMIT 1", (key,))
    return str(row["value"]) if row and row.get("value") else None


async def _set_runtime_value(repository, key: str, value: str) -> None:
    await repository.run(
        """
        INSERT INTO runtime_state(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (key, value),
    )


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
        SELECT b.id AS weekly_id,
               b.trade_date AS latest_weekly_date,
               b.source_document_id AS weekly_source_document_id,
               b.shares AS weekly_shares,
               b.amount_nok AS weekly_amount_nok,
               (SELECT MAX(trade_date) FROM buyback_daily_transactions) AS latest_daily_date
        FROM buybacks b
        ORDER BY b.trade_date DESC, b.id DESC
        LIMIT 1
        """
    ) or {}
    attachment = await _latest_current_parser_attachment(repository)
    completed_fingerprint = await _runtime_value(repository, _COMPLETED_WEEKLY_KEY)
    last_success = await _runtime_value(repository, _LAST_SUCCESS_KEY)
    return {
        "latest_weekly_date": row.get("latest_weekly_date"),
        "latest_daily_date": row.get("latest_daily_date"),
        "latest_weekly_fingerprint": _weekly_fingerprint(row),
        "completed_weekly_fingerprint": completed_fingerprint,
        "last_success_date": last_success,
        "attachment": attachment,
    }


def _revalidation_due(last_success: str | None, target_date: str) -> bool:
    if not last_success:
        return True
    try:
        success_day = date.fromisoformat(str(last_success)[:10])
        target = date.fromisoformat(target_date)
    except ValueError:
        return True
    return target - success_day >= timedelta(days=PDF_REVALIDATION_DAYS)


async def enrich_newsweb_buybacks_if_due(
    repository,
    bucket,
    *,
    target_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Run expensive PDF reconciliation only for changed coverage or periodic validation.

    The parser-versioned completion marker fingerprints the latest canonical weekly
    buyback row, so a same-date correction to economics/provenance also triggers a new
    PDF pass. Only a successful reconciliation advances the marker; missing
    transaction attachments and other partial/error runs remain retryable.
    """
    state = await _coverage_state(repository)
    weekly = str(state.get("latest_weekly_date") or "")
    daily = str(state.get("latest_daily_date") or "")
    latest_fingerprint = str(state.get("latest_weekly_fingerprint") or "")
    completed_fingerprint = str(state.get("completed_weekly_fingerprint") or "")
    last_success = str(state.get("last_success_date") or "")
    attachment = state.get("attachment")

    changed_weekly_coverage = bool(
        latest_fingerprint and latest_fingerprint != completed_fingerprint
    )
    revalidation_due = _revalidation_due(last_success or None, target_date)
    if not changed_weekly_coverage and not revalidation_due:
        metadata = (attachment or {}).get("metadata") or {}
        return {
            "status": "ok",
            "skipped": True,
            "reason": "pdf_coverage_current",
            "parser": PARSER_VERSION,
            "pdf_revalidation_days": PDF_REVALIDATION_DAYS,
            "latest_weekly_date": weekly or None,
            "latest_daily_date": daily or None,
            "last_success_date": last_success or None,
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
    if str(result.get("status") or "").lower() == "ok":
        if latest_fingerprint:
            await _set_runtime_value(repository, _COMPLETED_WEEKLY_KEY, latest_fingerprint)
        await _set_runtime_value(repository, _LAST_SUCCESS_KEY, target_date)

    return {
        **result,
        "skipped": False,
        "refresh_reason": (
            "weekly_fingerprint_changed"
            if changed_weekly_coverage
            else "periodic_hash_revalidation"
        ),
        "pdf_revalidation_days": PDF_REVALIDATION_DAYS,
        "last_success_before": last_success or None,
    }

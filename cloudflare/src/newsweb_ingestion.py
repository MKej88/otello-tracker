from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from newsweb_client import NewsWebMessage, discover_otec_messages, fetch_message
from repository import D1WriteRepository

DEFAULT_HISTORY_START = "2020-01-01"
INCREMENTAL_OVERLAP_DAYS = 14
_SPACE_RE = re.compile(r"\s+")


def _title(value: str) -> str:
    return _SPACE_RE.sub(" ", value.lower()).strip()


def classify_newsweb_message(message: NewsWebMessage) -> tuple[str, bool, str]:
    title = _title(message.title)
    if any(
        term in title
        for term in (
            "annual report",
            "quarterly report",
            "quarter report",
            "interim report",
            "half-year report",
            "half year report",
            "financial report",
            "financial results",
            "1q",
            "2q",
            "3q",
            "4q",
            "q1",
            "q2",
            "q3",
            "q4",
        )
    ):
        return "RESULTS", False, "result/report title"
    if any(
        term in title
        for term in (
            "buyback",
            "buy-back",
            "buy back",
            "purchase of own shares",
            "repurchase of shares",
        )
    ):
        return "BUYBACK", False, "buyback title"
    if "jcp" in title or "interest on own capital" in title:
        return "JCP", False, "JCP title"
    if any(
        term in title
        for term in (
            "cash dividend",
            "ex-dividend",
            "ex dividend",
            "dividend to be paid",
            "distribution to shareholders",
            "return of capital",
        )
    ):
        return "DIVIDEND", False, "distribution/dividend title"
    if any(
        term in title
        for term in (
            "share capital",
            "capital reduction",
            "share cancellation",
            "cancellation of shares",
            "cancellation of own shares",
            "treasury shares",
            "new share capital",
        )
    ):
        return "CAPITAL", False, "capital/share-count title"
    if any(
        term in title
        for term in (
            "definitive agreement to sell",
            "agreement to sell adcolony",
            "sale of adcolony",
            "completion of adcolony",
            "adcolony acquisition",
            "adcolony payment",
            "adcolony earnout",
            "settlement of adcolony",
            "bemobi ipo",
            "bemobi - result of the greenshoe",
            "bemobi trading commences",
            "filing for ipo",
            "acquisition of",
            "divestment of",
            "merger with",
        )
    ):
        return "M_AND_A", False, "explicit business transaction title"
    if any(term in title for term in ("financial outlook", "outlook update", "guidance", "profit warning")):
        return "GUIDANCE", False, "guidance/outlook title"
    if any(
        term in title
        for term in (
            "general meeting",
            "annual general meeting",
            "extraordinary general meeting",
            "agm",
            "egm",
            "financial calendar",
            "mandatory notification",
            "primary insider",
            "major shareholding",
            "large shareholder",
            "disclosure of shareholding",
            "notification of trade",
            "board of directors",
            "new ceo",
            "new cfo",
            "litigation",
            "lawsuit",
            "vewd",
        )
    ):
        return "CORPORATE", False, "corporate/governance title"
    return "OTHER", True, "no high-confidence title rule"


def _nav_impact(category: str) -> str:
    return "POTENTIAL" if category in {"DIVIDEND", "JCP", "BUYBACK", "M_AND_A", "CAPITAL", "GUIDANCE"} else "NONE"


def _metadata(message: NewsWebMessage, category: str, reason: str, review: bool) -> dict[str, Any]:
    return {
        "source_quality": "OFFICIAL_ORIGINAL",
        "newsweb_message_id": message.message_id,
        "news_id": message.news_id,
        "issuer_id": message.issuer_id,
        "issuer_sign": message.issuer_sign,
        "issuer_name": message.issuer_name,
        "markets": list(message.markets),
        "category_ids": list(message.category_ids),
        "attachments": [{"id": item.attachment_id, "name": item.name} for item in message.attachments],
        "attachment_count": len(message.attachments),
        "client_announcement_id": message.client_announcement_id,
        "correction_for_message_id": message.correction_for_message_id,
        "corrected_by_message_id": message.corrected_by_message_id,
        "body_length": len(message.body),
        "archive_category": category,
        "classification_reason": reason,
        "requires_review": review,
        "body_persisted": False,
        "worker_ingestion": True,
    }


async def _latest_archived_date(repository: D1WriteRepository) -> str | None:
    row = await repository.first(
        """
        SELECT MAX(substr(sd.published_at, 1, 10)) AS latest_date
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='NEWSWEB'
          AND sd.external_id LIKE 'newsweb-message:%'
          AND sd.document_type='REGULATORY_NEWS'
        """
    )
    return str(row["latest_date"]) if row and row.get("latest_date") else None


async def history_start_for_refresh(
    repository: D1WriteRepository,
    *,
    default_start: str = DEFAULT_HISTORY_START,
) -> str:
    latest = await _latest_archived_date(repository)
    if not latest:
        return default_start
    overlap = date.fromisoformat(latest) - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
    return max(default_start, overlap.isoformat())


async def archive_message(
    repository: D1WriteRepository,
    message: NewsWebMessage,
) -> dict[str, Any]:
    category, review, reason = classify_newsweb_message(message)
    document_id = await repository.create_source_document(
        source_code="NEWSWEB",
        external_id=f"newsweb-message:{message.message_id}",
        document_type="REGULATORY_NEWS",
        title=message.title,
        url=message.public_url,
        published_at=message.published_at,
        content_sha256=hashlib.sha256(message.body.encode("utf-8")).hexdigest(),
        metadata=_metadata(message, category, reason, review),
    )
    otec_id = await repository.instrument_id("OTEC")
    processing_status = "REVIEW_REQUIRED" if review else "PARSED"
    notes = f"NewsWeb archive classification: {reason}. Full message body is not persisted."
    await repository.run(
        """
        INSERT INTO company_news(
            issuer_instrument_id, source_document_id, headline, published_at,
            category, nav_impact, processing_status, summary, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
        ON CONFLICT(source_document_id) DO UPDATE SET
            issuer_instrument_id=excluded.issuer_instrument_id,
            headline=excluded.headline,
            published_at=excluded.published_at,
            category=excluded.category,
            nav_impact=excluded.nav_impact,
            processing_status=excluded.processing_status,
            summary=NULL,
            notes=excluded.notes,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (
            otec_id,
            document_id,
            message.title,
            message.published_at,
            category,
            _nav_impact(category),
            processing_status,
            notes,
        ),
    )
    row = await repository.first(
        "SELECT id FROM company_news WHERE source_document_id=? LIMIT 1",
        (document_id,),
    )
    if row is None:
        raise RuntimeError("NewsWeb company_news ble skrevet, men kunne ikke leses tilbake")
    return {
        "message_id": message.message_id,
        "source_document_id": document_id,
        "company_news_id": int(row["id"]),
        "category": category,
        "requires_review": review,
    }


async def collect_newsweb_history(
    repository: D1WriteRepository,
    *,
    to_date: str,
    from_date: str | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    start = from_date or await history_start_for_refresh(repository)
    discovered = await discover_otec_messages(start, to_date, fetcher=fetcher)
    archived: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for item in discovered:
        try:
            full = await fetch_message(item.message_id, fetcher=fetcher)
            archived.append(await archive_message(repository, full))
        except Exception as exc:
            errors.append(
                {
                    "message_id": item.message_id,
                    "published_at": item.published_at,
                    "title": item.title,
                    "error": str(exc)[:1000],
                }
            )
    categories = Counter(item["category"] for item in archived)
    return {
        "status": "error" if errors and not archived else ("partial" if errors else "ok"),
        "from": start,
        "to": to_date,
        "discovered": len(discovered),
        "archived": len(archived),
        "errors": errors,
        "requires_review": sum(1 for item in archived if item["requires_review"]),
        "categories": dict(sorted(categories.items())),
    }

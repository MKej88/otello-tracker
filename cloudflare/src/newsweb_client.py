from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

from bounded_response import read_response_bytes, read_response_text

API_BASE = "https://api3.oslo.oslobors.no/v1/newsreader"
WEB_BASE = "https://newsweb.oslobors.no"
OTEC_ISSUER_ID = 7759
OTEC_SIGN = "OTEC"
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class NewsWebAttachment:
    attachment_id: int
    name: str


@dataclass(frozen=True)
class NewsWebMessage:
    message_id: int
    news_id: int | None
    title: str
    body: str
    issuer_id: int
    issuer_sign: str
    issuer_name: str
    published_at: str
    markets: tuple[str, ...]
    category_ids: tuple[int, ...]
    attachments: tuple[NewsWebAttachment, ...]
    corrected_by_message_id: int
    correction_for_message_id: int
    client_announcement_id: str | None

    @property
    def public_url(self) -> str:
        return f"{WEB_BASE}/message/{self.message_id}"


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/",
        "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
    }


async def _post_json(
    url: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch

    response = await fetcher(
        url,
        method="POST",
        headers=_headers(),
        body="{}",
    )
    if not bool(getattr(response, "ok", False)):
        status = getattr(response, "status", "unknown")
        raise RuntimeError(f"NewsWeb API feilet med HTTP {status}")

    text = await read_response_text(
        response,
        max_bytes=MAX_JSON_BYTES,
        label="NewsWeb JSON-respons",
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("NewsWeb API returnerte ugyldig JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("NewsWeb API-respons er ikke et JSON-objekt")
    header = payload.get("header") or {}
    if int(header.get("result.val", 0)) != 0 or int(header.get("http.code", 200)) >= 400:
        raise ValueError(f"NewsWeb API-feil: {header}")
    return payload


def _message_from_dict(raw: dict[str, Any], *, require_body: bool) -> NewsWebMessage:
    message_id = int(raw.get("messageId") or raw.get("id") or 0)
    if message_id <= 0:
        raise ValueError("NewsWeb-melding mangler messageId")
    issuer_id = int(raw.get("issuerId") or 0)
    issuer_sign = str(raw.get("issuerSign") or "").strip().upper()
    if issuer_id != OTEC_ISSUER_ID or issuer_sign != OTEC_SIGN:
        raise ValueError(
            f"NewsWeb-melding {message_id} tilhører ikke OTEC: issuerId={issuer_id}, sign={issuer_sign}"
        )
    markets = tuple(str(item) for item in (raw.get("markets") or []))
    if markets and "XOSL" not in markets:
        raise ValueError(f"NewsWeb-melding {message_id} mangler XOSL-marked")
    body = str(raw.get("body") or "")
    if require_body and not body.strip():
        raise ValueError(f"NewsWeb-melding {message_id} mangler meldingstekst")
    attachments = tuple(
        NewsWebAttachment(int(item["id"]), str(item.get("name") or ""))
        for item in (raw.get("attachments") or [])
        if item.get("id") is not None
    )
    category_ids = tuple(
        int(item["id"])
        for item in (raw.get("category") or [])
        if item.get("id") is not None
    )
    return NewsWebMessage(
        message_id=message_id,
        news_id=int(raw["newsId"]) if raw.get("newsId") is not None else None,
        title=str(raw.get("title") or ""),
        body=body,
        issuer_id=issuer_id,
        issuer_sign=issuer_sign,
        issuer_name=str(raw.get("issuerName") or ""),
        published_at=str(raw.get("publishedTime") or ""),
        markets=markets,
        category_ids=category_ids,
        attachments=attachments,
        corrected_by_message_id=int(raw.get("correctedByMessageId") or 0),
        correction_for_message_id=int(raw.get("correctionForMessageId") or 0),
        client_announcement_id=(
            str(raw["clientAnnouncementId"]) if raw.get("clientAnnouncementId") else None
        ),
    )


def parse_message_payload(payload: dict[str, Any]) -> NewsWebMessage:
    try:
        raw = payload["data"]["message"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Uventet NewsWeb message-respons") from exc
    return _message_from_dict(raw, require_body=True)


def parse_list_payload(payload: dict[str, Any]) -> tuple[list[NewsWebMessage], bool]:
    try:
        data = payload["data"]
        raw_messages = data["messages"]
        overflow = data["overflow"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Uventet NewsWeb list-respons") from exc
    if not isinstance(raw_messages, list) or not isinstance(overflow, bool):
        raise ValueError("Uventet NewsWeb list-respons")
    if not all(isinstance(item, dict) for item in raw_messages):
        raise ValueError("Uventet NewsWeb list-respons")
    messages = [_message_from_dict(item, require_body=False) for item in raw_messages]
    return messages, overflow


async def fetch_message(
    message_id: int,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> NewsWebMessage:
    payload = await _post_json(
        f"{API_BASE}/message?messageId={int(message_id)}",
        fetcher=fetcher,
    )
    message = parse_message_payload(payload)
    if message.message_id != int(message_id):
        raise ValueError(
            f"NewsWeb returnerte messageId {message.message_id}, forventet {message_id}"
        )
    return message


def attachment_url(message_id: int, attachment_id: int) -> str:
    return (
        f"{API_BASE}/attachment?messageId={int(message_id)}"
        f"&attachmentId={int(attachment_id)}"
    )


async def fetch_attachment(
    message_id: int,
    attachment_id: int,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> bytes:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    url = attachment_url(message_id, attachment_id)
    response = await fetcher(
        url,
        headers={
            "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
            "Origin": WEB_BASE,
            "Referer": f"{WEB_BASE}/message/{int(message_id)}",
            "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
        },
    )
    if not bool(getattr(response, "ok", False)):
        status = getattr(response, "status", "unknown")
        raise RuntimeError(
            f"NewsWeb attachment {message_id}/{attachment_id} feilet med HTTP {status}"
        )
    payload = await read_response_bytes(
        response,
        max_bytes=MAX_ATTACHMENT_BYTES,
        label=f"NewsWeb attachment {message_id}/{attachment_id}",
    )
    if not payload.startswith(b"%PDF"):
        raise ValueError(f"NewsWeb attachment {message_id}/{attachment_id} er ikke en PDF")
    return payload


async def _list_window(
    start: date,
    end: date,
    *,
    message_title: str,
    fetcher: Callable[..., Awaitable[Any]] | None,
) -> tuple[list[NewsWebMessage], bool]:
    params = {
        "category": "",
        "issuer": str(OTEC_ISSUER_ID),
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
        "market": "",
        "messageTitle": message_title,
    }
    url = f"{API_BASE}/list?{urlencode(params)}"
    return parse_list_payload(await _post_json(url, fetcher=fetcher))


async def _discover_window(
    start: date,
    end: date,
    *,
    message_title: str,
    fetcher: Callable[..., Awaitable[Any]] | None,
) -> list[NewsWebMessage]:
    messages, overflow = await _list_window(
        start,
        end,
        message_title=message_title,
        fetcher=fetcher,
    )
    if not overflow:
        return messages
    if start >= end:
        raise ValueError(f"NewsWeb list overflow på enkelt dato {start.isoformat()}")
    midpoint = start + timedelta(days=(end - start).days // 2)
    left = await _discover_window(
        start,
        midpoint,
        message_title=message_title,
        fetcher=fetcher,
    )
    right = await _discover_window(
        midpoint + timedelta(days=1),
        end,
        message_title=message_title,
        fetcher=fetcher,
    )
    return left + right


async def discover_otec_messages(
    from_date: str,
    to_date: str,
    *,
    message_title: str = "",
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> list[NewsWebMessage]:
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    if start > end:
        raise ValueError("from_date kan ikke være etter to_date")
    found = await _discover_window(
        start,
        end,
        message_title=message_title,
        fetcher=fetcher,
    )
    unique: dict[int, NewsWebMessage] = {}
    for message in found:
        if message.corrected_by_message_id:
            continue
        unique[message.message_id] = message
    return sorted(unique.values(), key=lambda item: (item.published_at, item.message_id))

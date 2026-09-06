from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

try:
    from .bemobi_news_quality import (
        classify_media_item,
        media_paywall_likely,
        media_should_be_shown,
        media_story_key,
    )
    from .bounded_response import read_response_bytes
except ImportError:
    from bemobi_news_quality import (
        classify_media_item,
        media_paywall_likely,
        media_should_be_shown,
        media_story_key,
    )
    from bounded_response import read_response_bytes

MEDIA_SOURCE_CODE = "BRAZIL_MEDIA"
MEDIA_SOURCE_NAME = "Brasiliansk medieomtale"
TRANSLATION_MODEL = "@cf/meta/m2m100-1.2b"
MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_NEW_ARTICLES_PER_RUN = 8
INITIAL_BACKFILL_MAX_ARTICLES = 24
MEDIA_LOOKBACK_DAYS = 30
USER_AGENT = "otello-tracker/1.0 private-investor-dashboard"

GOOGLE_NEWS_SOURCE = "Google News Brasil"
BING_NEWS_SOURCE = "Bing News Brasil"
SEARCH_TERMS = ("Bemobi", "BMOB3", '"Pedro Ripper"')


def _google_news_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query + f" when:{MEDIA_LOOKBACK_DAYS}d")
        + "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    )


def _bing_news_url(query: str) -> str:
    return (
        "https://www.bing.com/news/search?q="
        + quote_plus(query)
        + "&format=RSS&setlang=pt-br&cc=br"
    )


GOOGLE_NEWS_RSS_URLS = tuple(_google_news_url(term) for term in SEARCH_TERMS)
BING_NEWS_RSS_URLS = tuple(_bing_news_url(term) for term in SEARCH_TERMS)
# Compatibility aliases used by tests and diagnostics.
GOOGLE_NEWS_RSS_URL = GOOGLE_NEWS_RSS_URLS[0]
BING_NEWS_RSS_URL = BING_NEWS_RSS_URLS[0]
SEARCH_FEED_SOURCES = frozenset({GOOGLE_NEWS_SOURCE, BING_NEWS_SOURCE})

# Direct publisher feeds give richer snippets when available. Search feeds are
# deliberately duplicated across Google/Bing for coverage, but query membership
# alone is never treated as proof that an item is relevant.
FEEDS = (
    ("InfoMoney", "https://www.infomoney.com.br/feed/"),
    ("NeoFeed", "https://neofeed.com.br/feed/"),
    ("Brazil Journal", "https://braziljournal.com/feed/"),
    ("CNN Brasil", "https://www.cnnbrasil.com.br/tudo-sobre/economia/feed/"),
    *((GOOGLE_NEWS_SOURCE, url) for url in GOOGLE_NEWS_RSS_URLS),
    *((BING_NEWS_SOURCE, url) for url in BING_NEWS_RSS_URLS),
)

_ILLEGAL_XML_BYTES = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_BARE_AMPERSAND_BYTES = re.compile(
    rb"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]+;)"
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


def _strip_html(value: Any) -> str:
    text = str(value or "")
    if "<" not in text:
        return _clean(text)
    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return _clean(re.sub(r"<[^>]+>", " ", text))
    return _clean(" ".join(parser.parts))


def _repair_xml_payload(payload: bytes) -> bytes:
    """Repair common publisher-feed XML defects without changing valid XML."""
    repaired = _ILLEGAL_XML_BYTES.sub(b"", payload)
    return _BARE_AMPERSAND_BYTES.sub(b"&amp;", repaired)


def _parse_xml_root(payload: bytes) -> ET.Element:
    try:
        return ET.fromstring(payload)
    except ET.ParseError as original_error:
        repaired = _repair_xml_payload(payload)
        if repaired == payload:
            raise original_error
        return ET.fromstring(repaired)


def _tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def _child_text(element: ET.Element, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for child in element.iter():
        if child is element:
            continue
        if _tag_name(child) in wanted:
            value = _clean(child.text)
            if value:
                return value
    return None


def _child_markup_text(element: ET.Element, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for child in element.iter():
        if child is element:
            continue
        if _tag_name(child) in wanted:
            rendered = "".join(child.itertext())
            value = _strip_html(rendered or child.text)
            if value:
                return value
    return None


def _entry_link(element: ET.Element) -> str | None:
    # RSS normally uses text in <link>; Atom normally uses href.
    for child in element:
        if _tag_name(child) != "link":
            continue
        href = _clean(child.attrib.get("href"))
        if href.startswith(("https://", "http://")):
            return href
        value = _clean(child.text)
        if value.startswith(("https://", "http://")):
            return value
    return None


def _publisher(element: ET.Element, fallback: str) -> str:
    for child in element.iter():
        if _tag_name(child) == "source":
            value = _clean(child.text)
            if value:
                return value
    author = _child_text(element, "author", "creator", "name")
    return author or fallback


def _published_iso(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _within_lookback(published_at: str | None, *, now: datetime | None = None) -> bool:
    """Keep search-engine results inside the same 30-day window used by Google News."""
    if not published_at:
        return True
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    published = published.astimezone(UTC)
    return current - timedelta(days=MEDIA_LOOKBACK_DAYS) <= published <= current + timedelta(days=1)


def _parse_feed(
    payload: bytes,
    *,
    fallback_source: str,
    feed_url: str,
) -> list[dict[str, Any]]:
    root = _parse_xml_root(payload)
    entries = [node for node in root.iter() if _tag_name(node) in {"item", "entry"}]
    articles: list[dict[str, Any]] = []
    for entry in entries:
        title = _child_text(entry, "title")
        link = _entry_link(entry)
        if not title or not link:
            continue
        summary = _child_markup_text(entry, "description", "summary", "encoded", "content")
        publisher = _publisher(entry, fallback_source)
        if not media_should_be_shown(title=title, summary=summary, publisher=publisher):
            continue
        published = _published_iso(
            _child_text(entry, "pubdate", "published", "updated", "date")
        )
        articles.append(
            {
                "title": _clean(title),
                "summary": _clean(summary) if summary else None,
                "url": link,
                "published_at": published,
                "publisher": publisher,
                "feed_source": fallback_source,
                "feed_url": feed_url,
            }
        )
    return articles


def _article_external_id(article: dict[str, Any]) -> str:
    basis = "|".join(
        (
            str(article.get("publisher") or "").casefold(),
            str(article.get("title") or "").casefold(),
            str(article.get("published_at") or "")[:10],
        )
    )
    return "media-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


async def _fetch_feed(url: str, *, fetcher=None) -> bytes:
    if fetcher is None:
        from workers import fetch as workers_fetch

        fetcher = workers_fetch
    response = await fetcher(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
        },
    )
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(f"HTTP {getattr(response, 'status', 'unknown')} for {url}")
    return await read_response_bytes(response, max_bytes=MAX_FEED_BYTES, label=url)


def _translated_text(result: Any) -> str | None:
    value = None
    if isinstance(result, dict):
        value = result.get("translated_text")
    else:
        try:
            value = result["translated_text"]
        except (KeyError, TypeError, AttributeError):
            value = getattr(result, "translated_text", None)
    translated = _clean(value)
    return translated or None


async def _translate(ai_binding: Any, text: str) -> str:
    result = await ai_binding.run(
        TRANSLATION_MODEL,
        {
            "text": text[:2400],
            "source_lang": "portuguese",
            "target_lang": "english",
        },
    )
    translated = _translated_text(result)
    if not translated:
        raise RuntimeError("Workers AI translation returned no translated_text")
    return translated


def _useful_summary(summary: str | None, title: str, publisher: str) -> str | None:
    value = _clean(summary)
    if not value:
        return None
    simplified = value.casefold()
    title_cf = _clean(title).casefold()
    publisher_cf = _clean(publisher).casefold()
    if simplified in {title_cf, publisher_cf, f"{title_cf} {publisher_cf}"}:
        return None
    if simplified.startswith(title_cf) and len(value) <= len(title) + len(publisher) + 20:
        return None
    return value[:1200]


async def _ensure_source(repository) -> int:
    await repository.run(
        """
        INSERT INTO sources(code, name, source_type, base_url, is_official, is_active)
        VALUES (?, ?, 'OTHER', 'https://news.google.com/', 0, 1)
        ON CONFLICT(code) DO UPDATE SET
            name=excluded.name, source_type=excluded.source_type,
            base_url=excluded.base_url, is_active=1
        """,
        (MEDIA_SOURCE_CODE, MEDIA_SOURCE_NAME),
    )
    row = await repository.first("SELECT id FROM sources WHERE code=? LIMIT 1", (MEDIA_SOURCE_CODE,))
    if row is None:
        raise RuntimeError("Could not resolve BRAZIL_MEDIA source")
    return int(row["id"])


async def _bemobi_instrument_id(repository) -> int:
    row = await repository.first("SELECT id FROM instruments WHERE symbol='BMOB3' LIMIT 1")
    if row is None:
        raise RuntimeError("BMOB3 instrument missing")
    return int(row["id"])


async def _existing_media_count(repository, source_id: int) -> int:
    row = await repository.first(
        """
        SELECT COUNT(*) AS count
        FROM source_documents
        WHERE source_id=? AND document_type='MEDIA_ARTICLE'
        """,
        (source_id,),
    )
    return int((row or {}).get("count") or 0)


async def _already_seen(repository, source_id: int, external_id: str) -> bool:
    row = await repository.first(
        "SELECT id FROM source_documents WHERE source_id=? AND external_id=? LIMIT 1",
        (source_id, external_id),
    )
    return row is not None


async def _insert_article(
    repository,
    *,
    source_id: int,
    instrument_id: int,
    article: dict[str, Any],
    english_title: str,
    english_summary: str | None,
) -> None:
    external_id = _article_external_id(article)
    metadata = {
        "content_type": "MEDIA",
        "publisher": article.get("publisher"),
        "original_title": article.get("title"),
        "original_summary": article.get("summary"),
        "original_language": "pt-BR",
        "translation_model": TRANSLATION_MODEL,
        "feed_source": article.get("feed_source"),
        "feed_url": article.get("feed_url"),
        "original_url": article.get("url"),
        "paywall_likely": media_paywall_likely(article.get("publisher")),
    }
    content_hash = hashlib.sha256(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    await repository.run(
        """
        INSERT INTO source_documents(
            source_id, external_id, document_type, title, published_at,
            url, content_sha256, metadata_json
        ) VALUES (?, ?, 'MEDIA_ARTICLE', ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, external_id) DO NOTHING
        """,
        (
            source_id,
            external_id,
            article["title"],
            article.get("published_at"),
            article["url"],
            content_hash,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        ),
    )
    document = await repository.first(
        "SELECT id FROM source_documents WHERE source_id=? AND external_id=? LIMIT 1",
        (source_id, external_id),
    )
    if document is None:
        raise RuntimeError("Media source document was not persisted")
    category, nav_impact = classify_media_item(article.get("title"), article.get("summary"))
    await repository.run(
        """
        INSERT INTO company_news(
            issuer_instrument_id, source_document_id, headline, published_at,
            category, nav_impact, processing_status, summary, notes
        ) VALUES (?, ?, ?, ?, ?, ?, 'APPLIED', ?, ?)
        ON CONFLICT(source_document_id) DO NOTHING
        """,
        (
            instrument_id,
            int(document["id"]),
            english_title,
            article.get("published_at"),
            category,
            nav_impact,
            english_summary,
            "Automatic English translation of Brazilian media RSS metadata; original source retained.",
        ),
    )


async def refresh_bemobi_media_news(
    repository,
    *,
    ai_binding: Any | None,
    fetcher=None,
    max_new_articles: int | None = None,
) -> dict[str, Any]:
    """Fetch investor-relevant Brazilian Bemobi media and store English renderings.

    Google News and Bing are discovery sources only: every result must independently mention
    Bemobi, BMOB3 or Pedro Ripper in its RSS metadata. Quote pages, charts, technical-analysis
    pages, company profiles and disclaimer pages are filtered before translation. Generic
    paywalled mentions are also removed, while material paywalled stories are retained and
    marked. Headlines are conservatively deduplicated across feeds within the same date.

    Only RSS/Atom metadata is ingested. Full article bodies and paywalled content are not copied.
    Failures are best-effort and must never block market-data refreshes.
    """
    if ai_binding is None:
        return {
            "status": "skipped",
            "reason": "workers_ai_binding_unavailable",
            "written": 0,
            "feeds_checked": 0,
            "feeds_succeeded": 0,
            "candidates": 0,
            "skipped_existing": 0,
            "feed_errors": [],
            "translation_errors": [],
            "window_days": MEDIA_LOOKBACK_DAYS,
            "initial_backfill": False,
            "article_limit": 0,
        }

    source_id = await _ensure_source(repository)
    instrument_id = await _bemobi_instrument_id(repository)
    existing_before = await _existing_media_count(repository, source_id)
    initial_backfill = existing_before == 0
    article_limit = (
        max(1, int(max_new_articles))
        if max_new_articles is not None
        else INITIAL_BACKFILL_MAX_ARTICLES if initial_backfill else MAX_NEW_ARTICLES_PER_RUN
    )
    feed_errors: list[dict[str, str]] = []
    candidates: dict[str, dict[str, Any]] = {}
    feeds_succeeded = 0
    search_now = datetime.now(UTC)

    for feed_source, feed_url in FEEDS:
        try:
            payload = await _fetch_feed(feed_url, fetcher=fetcher)
            articles = _parse_feed(
                payload,
                fallback_source=feed_source,
                feed_url=feed_url,
            )
        except Exception as exc:
            feed_errors.append(
                {
                    "source": feed_source,
                    "error": str(exc)[:400] or type(exc).__name__,
                    "error_type": type(exc).__name__,
                }
            )
            continue
        feeds_succeeded += 1
        for article in articles:
            if feed_source in SEARCH_FEED_SOURCES and not _within_lookback(
                article.get("published_at"), now=search_now
            ):
                continue
            story_key = media_story_key(article.get("title"), article.get("published_at"))
            candidates.setdefault(story_key, article)

    ordered = sorted(
        candidates.values(),
        key=lambda item: str(item.get("published_at") or ""),
        reverse=True,
    )
    written = 0
    skipped_existing = 0
    translation_errors: list[dict[str, str]] = []

    for article in ordered:
        if written >= article_limit:
            break
        external_id = _article_external_id(article)
        if await _already_seen(repository, source_id, external_id):
            skipped_existing += 1
            continue
        try:
            english_title = await _translate(ai_binding, article["title"])
            useful_summary = _useful_summary(
                article.get("summary"), article["title"], article.get("publisher") or ""
            )
            english_summary = (
                await _translate(ai_binding, useful_summary) if useful_summary else None
            )
            await _insert_article(
                repository,
                source_id=source_id,
                instrument_id=instrument_id,
                article=article,
                english_title=english_title,
                english_summary=english_summary,
            )
            written += 1
        except Exception as exc:
            translation_errors.append(
                {
                    "title": str(article.get("title") or "")[:160],
                    "error": str(exc)[:400] or type(exc).__name__,
                    "error_type": type(exc).__name__,
                }
            )

    status = "ok"
    if translation_errors or feed_errors:
        status = "partial" if feeds_succeeded > 0 else "error"
    return {
        "status": status,
        "written": written,
        "feeds_checked": len(FEEDS),
        "feeds_succeeded": feeds_succeeded,
        "candidates": len(candidates),
        "skipped_existing": skipped_existing,
        "feed_errors": feed_errors,
        "translation_errors": translation_errors,
        "translation_model": TRANSLATION_MODEL,
        "window_days": MEDIA_LOOKBACK_DAYS,
        "initial_backfill": initial_backfill,
        "existing_before": existing_before,
        "article_limit": article_limit,
    }

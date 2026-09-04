from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

try:
    from .bounded_response import read_response_bytes
except ImportError:
    from bounded_response import read_response_bytes

MEDIA_SOURCE_CODE = "BRAZIL_MEDIA"
MEDIA_SOURCE_NAME = "Brasiliansk medieomtale"
TRANSLATION_MODEL = "@cf/meta/m2m100-1.2b"
MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_NEW_ARTICLES_PER_RUN = 8
USER_AGENT = "otello-tracker/1.0 private-investor-dashboard"

GOOGLE_NEWS_QUERY = '"Bemobi" OR BMOB3 OR "Pedro Ripper"'
GOOGLE_NEWS_RSS_URL = (
    "https://news.google.com/rss/search?q="
    + quote_plus(GOOGLE_NEWS_QUERY + " when:30d")
    + "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
)

# Direct feeds give richer publisher snippets when available. Google News is the
# catch-all for Valor, Mobile Time, Bloomberg Linea and other Brazilian outlets.
FEEDS = (
    ("InfoMoney", "https://www.infomoney.com.br/feed/"),
    ("NeoFeed", "https://neofeed.com.br/feed/"),
    ("Brazil Journal", "https://braziljournal.com/feed/"),
    ("CNN Brasil", "https://www.cnnbrasil.com.br/tudo-sobre/economia/feed/"),
    ("Google News Brasil", GOOGLE_NEWS_RSS_URL),
)

_RELEVANCE_TERMS = ("bemobi", "bmob3", "pedro ripper")


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


def _is_relevant(title: Any, summary: Any = None) -> bool:
    haystack = f"{_clean(title)} {_strip_html(summary)}".casefold()
    return any(term in haystack for term in _RELEVANCE_TERMS)


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


def _parse_feed(payload: bytes, *, fallback_source: str, feed_url: str) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    entries = [node for node in root.iter() if _tag_name(node) in {"item", "entry"}]
    articles: list[dict[str, Any]] = []
    for entry in entries:
        title = _child_text(entry, "title")
        link = _entry_link(entry)
        if not title or not link:
            continue
        summary = _child_markup_text(entry, "description", "summary", "encoded", "content")
        if not _is_relevant(title, summary):
            continue
        published = _published_iso(
            _child_text(entry, "pubdate", "published", "updated", "date")
        )
        publisher = _publisher(entry, fallback_source)
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


def _category(title: str) -> tuple[str, str]:
    lowered = title.casefold()
    if any(term in lowered for term in ("resultado", "resultados", "balanço", "balanco", "lucro")):
        return "RESULTS", "POTENTIAL"
    if any(term in lowered for term in ("aquisição", "aquisicao", "adquire", "fusão", "fusao", "m&a")):
        return "M_AND_A", "POTENTIAL"
    if "recompra" in lowered:
        return "BUYBACK", "POTENTIAL"
    if "juros sobre capital" in lowered or "jcp" in lowered:
        return "JCP", "POTENTIAL"
    if "dividendo" in lowered:
        return "DIVIDEND", "POTENTIAL"
    return "OTHER", "POTENTIAL"


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
    category, nav_impact = _category(str(article.get("title") or ""))
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
    max_new_articles: int = MAX_NEW_ARTICLES_PER_RUN,
) -> dict[str, Any]:
    """Fetch relevant Brazilian Bemobi media and store English renderings.

    Only RSS/Atom metadata is ingested. Full article bodies and paywalled content are not copied.
    Failures are best-effort and must never block market-data refreshes.
    """
    if ai_binding is None:
        return {
            "status": "skipped",
            "reason": "workers_ai_binding_unavailable",
            "written": 0,
            "feeds_checked": 0,
            "errors": [],
        }

    source_id = await _ensure_source(repository)
    instrument_id = await _bemobi_instrument_id(repository)
    feed_errors: list[dict[str, str]] = []
    candidates: dict[str, dict[str, Any]] = {}

    for feed_source, feed_url in FEEDS:
        try:
            payload = await _fetch_feed(feed_url, fetcher=fetcher)
            articles = _parse_feed(payload, fallback_source=feed_source, feed_url=feed_url)
        except Exception as exc:
            feed_errors.append(
                {
                    "source": feed_source,
                    "error": str(exc)[:400] or type(exc).__name__,
                    "error_type": type(exc).__name__,
                }
            )
            continue
        for article in articles:
            candidates.setdefault(_article_external_id(article), article)

    ordered = sorted(
        candidates.values(),
        key=lambda item: str(item.get("published_at") or ""),
        reverse=True,
    )
    written = 0
    skipped_existing = 0
    translation_errors: list[dict[str, str]] = []

    for article in ordered:
        if written >= max(1, int(max_new_articles)):
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
        status = "partial" if written or candidates else "error"
    return {
        "status": status,
        "written": written,
        "feeds_checked": len(FEEDS),
        "candidates": len(candidates),
        "skipped_existing": skipped_existing,
        "feed_errors": feed_errors,
        "translation_errors": translation_errors,
        "translation_model": TRANSLATION_MODEL,
    }

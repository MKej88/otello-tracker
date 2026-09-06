from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
FRONTEND_SRC = ROOT / "frontend" / "src"


def _media_module():
    path = str(CLOUDFLARE_SRC)
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module("bemobi_media_news")


def test_media_feed_parser_keeps_only_relevant_bemobi_articles() -> None:
    media = _media_module()
    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss version='2.0'><channel>
      <item>
        <title>Bemobi acelera pagamentos no Brasil</title>
        <link>https://example.com/bemobi</link>
        <description><![CDATA[Bemobi amplia sua presenca em pagamentos recorrentes.]]></description>
        <pubDate>Thu, 03 Sep 2026 12:00:00 GMT</pubDate>
        <source>InfoMoney</source>
      </item>
      <item>
        <title>Outra empresa divulga resultados</title>
        <link>https://example.com/other</link>
        <description>Sem relacao com a companhia acompanhada.</description>
        <pubDate>Thu, 03 Sep 2026 11:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    articles = media._parse_feed(
        payload,
        fallback_source="fixture",
        feed_url="https://example.com/feed",
    )

    assert len(articles) == 1
    assert articles[0]["publisher"] == "InfoMoney"
    assert articles[0]["url"] == "https://example.com/bemobi"
    assert articles[0]["published_at"] == "2026-09-03T12:00:00Z"


def test_media_feed_parser_repairs_common_invalid_xml_tokens() -> None:
    media = _media_module()
    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss version='2.0'><channel>
      <item>
        <title>Bemobi & pagamentos recorrentes</title>
        <link>https://example.com/bemobi-invalid-xml</link>
        <description>Bemobi cresce no Brasil.</description>
        <pubDate>Fri, 04 Sep 2026 12:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    articles = media._parse_feed(
        payload,
        fallback_source="fixture",
        feed_url="https://example.com/feed",
    )

    assert len(articles) == 1
    assert articles[0]["title"] == "Bemobi & pagamentos recorrentes"


def test_bing_is_the_production_search_feed_and_google_is_only_compatibility() -> None:
    media = _media_module()

    assert media.SEARCH_TERMS == ("Bemobi", "BMOB3", '"Pedro Ripper"')
    assert len(media.GOOGLE_NEWS_RSS_URLS) == 3
    assert len(media.BING_NEWS_RSS_URLS) == 3
    assert all("news.google.com/rss/search" in url for url in media.GOOGLE_NEWS_RSS_URLS)
    assert all("when%3A30d" in url for url in media.GOOGLE_NEWS_RSS_URLS)
    assert all("bing.com/news/search" in url for url in media.BING_NEWS_RSS_URLS)
    assert all("format=RSS" in url for url in media.BING_NEWS_RSS_URLS)
    assert media.GOOGLE_NEWS_SOURCE not in media.SEARCH_FEED_SOURCES
    assert media.BING_NEWS_SOURCE in media.SEARCH_FEED_SOURCES
    assert len(media.FEEDS) == 6
    assert all(source != "CNN Brasil" for source, _ in media.FEEDS)
    assert all(source != media.GOOGLE_NEWS_SOURCE for source, _ in media.FEEDS)


def test_search_results_are_constrained_to_30_day_window() -> None:
    media = _media_module()
    now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

    assert media._within_lookback("2026-08-06T12:00:00Z", now=now) is True
    assert media._within_lookback("2026-08-05T11:59:59Z", now=now) is False
    assert media._within_lookback(None, now=now) is True


def test_search_feed_requires_explicit_bemobi_relevance_in_metadata() -> None:
    media = _media_module()
    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss version='2.0'><channel>
      <item>
        <title>Small caps tambem vao surfar onda de otimismo?</title>
        <link>https://news.example/articles/example</link>
        <description>Veja as empresas mais recomendadas pelos analistas.</description>
        <pubDate>Fri, 04 Sep 2026 08:00:00 GMT</pubDate>
        <source>InfoMoney</source>
      </item>
    </channel></rss>"""

    direct_articles = media._parse_feed(
        payload,
        fallback_source="InfoMoney",
        feed_url="https://www.infomoney.com.br/feed/",
    )
    google_articles = media._parse_feed(
        payload,
        fallback_source=media.GOOGLE_NEWS_SOURCE,
        feed_url=media.GOOGLE_NEWS_RSS_URL,
    )
    bing_articles = media._parse_feed(
        payload,
        fallback_source=media.BING_NEWS_SOURCE,
        feed_url=media.BING_NEWS_RSS_URL,
    )

    assert direct_articles == []
    assert google_articles == []
    assert bing_articles == []


def test_bemobi_media_ingestion_is_translated_deduplicated_and_metadata_only() -> None:
    media_source = (CLOUDFLARE_SRC / "bemobi_media_news.py").read_text(encoding="utf-8")
    worker_source = (CLOUDFLARE_SRC / "worker.py").read_text(encoding="utf-8")
    news_source = (CLOUDFLARE_SRC / "news_events.py").read_text(encoding="utf-8")
    frontend_source = (FRONTEND_SRC / "NewsEventsPage.tsx").read_text(encoding="utf-8")
    config = json.loads((ROOT / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8"))

    assert 'TRANSLATION_MODEL = "@cf/meta/m2m100-1.2b"' in media_source
    assert 'MEDIA_LOOKBACK_DAYS = 30' in media_source
    assert 'INITIAL_BACKFILL_MAX_ARTICLES = 24' in media_source
    assert 'BING_NEWS_SOURCE = "Bing News Brasil"' in media_source
    assert 'SEARCH_TERMS = ("Bemobi", "BMOB3", \'"Pedro Ripper"\')' in media_source
    assert "GOOGLE_NEWS_RSS_URLS" in media_source
    assert "BING_NEWS_RSS_URLS" in media_source
    assert "media_should_be_shown" in media_source
    assert "story_key = media_story_key" in media_source
    assert "media_paywall_likely" in media_source
    assert "_within_lookback" in media_source
    assert "_repair_xml_payload" in media_source
    assert "feeds_succeeded += 1" in media_source
    assert 'status = "partial" if feeds_succeeded > 0 else "error"' in media_source
    assert '"source_lang": "portuguese"' in media_source
    assert '"target_lang": "english"' in media_source
    assert '"content_type": "MEDIA"' in media_source
    assert '"original_title"' in media_source
    assert '"original_summary"' in media_source
    assert '"original_url"' in media_source
    assert '"paywall_likely"' in media_source
    assert "Full article bodies and paywalled content are not copied" in media_source
    assert "_article_external_id" in media_source
    assert "ON CONFLICT(source_id, external_id) DO NOTHING" in media_source

    assert "refresh_bemobi_media_news" in worker_source
    assert 'FAST_REFRESH_CRON = "*/30 * * * *"' in worker_source
    assert 'MEDIA_JOB_NAME = "bemobi_media_refresh"' in worker_source
    assert "repository.start_job" in worker_source
    assert "repository.finish_job" in worker_source
    assert '"non_critical": True' in worker_source
    assert config["ai"]["binding"] == "AI"

    assert 'content_type": "MEDIA" if is_media else "OFFICIAL"' in news_source
    assert "classify_media_item" in news_source
    assert "media_should_be_shown" in news_source
    assert "seen_media_stories" in news_source
    assert 'metadata.get("publisher")' in news_source
    assert '"media_status": media_status' in news_source
    assert '"failed_sources": failed_sources' in news_source
    assert '"nav_impact": nav_impact' in news_source
    assert '"paywall_likely": paywall_likely' in news_source

    assert 'type ContentFilter = "Alle" | "Viktige" | "Offisielt" | "Media"' in frontend_source
    assert 'media_status?: MediaStatus' in frontend_source
    assert 'failed_sources?: string[]' in frontend_source
    assert 'paywall_likely?: boolean' in frontend_source
    assert "mediaDegraded" in frontend_source
    assert 'MEDIAINNHENTING' not in frontend_source
    assert 'mediaRefreshMetrics' not in frontend_source
    assert 'contentTypeBadge' not in frontend_source
    assert 'Automatisk oversatt fra portugisisk · basert på RSS-metadata' in frontend_source
    assert 'className="paywallBadge">Betalingsmur' in frontend_source
    assert '<SourceLink source={item.source} url={item.url} />' in frontend_source

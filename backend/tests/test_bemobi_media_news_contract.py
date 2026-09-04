from __future__ import annotations

import importlib
import json
import sys
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


def test_bemobi_media_ingestion_is_translated_deduplicated_and_metadata_only() -> None:
    media_source = (CLOUDFLARE_SRC / "bemobi_media_news.py").read_text(encoding="utf-8")
    worker_source = (CLOUDFLARE_SRC / "worker.py").read_text(encoding="utf-8")
    news_source = (CLOUDFLARE_SRC / "news_events.py").read_text(encoding="utf-8")
    frontend_source = (FRONTEND_SRC / "NewsEventsPage.tsx").read_text(encoding="utf-8")
    config = json.loads((ROOT / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8"))

    assert 'TRANSLATION_MODEL = "@cf/meta/m2m100-1.2b"' in media_source
    assert '"source_lang": "portuguese"' in media_source
    assert '"target_lang": "english"' in media_source
    assert '"content_type": "MEDIA"' in media_source
    assert '"original_title"' in media_source
    assert '"original_summary"' in media_source
    assert '"original_url"' in media_source
    assert "Full article bodies and paywalled content are not copied" in media_source
    assert "_article_external_id" in media_source
    assert "ON CONFLICT(source_id, external_id) DO NOTHING" in media_source

    assert "refresh_bemobi_media_news" in worker_source
    assert 'FAST_REFRESH_CRON = "*/30 * * * *"' in worker_source
    assert '"non_critical": True' in worker_source
    assert config["ai"]["binding"] == "AI"

    assert 'content_type": "MEDIA" if is_media else "OFFICIAL"' in news_source
    assert "and not is_media" in news_source
    assert 'metadata.get("publisher")' in news_source

    assert 'type ContentFilter = "Alle typer" | "Offisielt" | "Media"' in frontend_source
    assert 'contentTypeBadge' in frontend_source
    assert 'Automatically translated from Portuguese' in frontend_source
    assert 'originalkilden er alltid tilgjengelig' in frontend_source

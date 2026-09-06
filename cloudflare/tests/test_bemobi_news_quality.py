from __future__ import annotations

import sys
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from bemobi_news_quality import (  # noqa: E402
    classify_media_item,
    media_is_relevant,
    media_paywall_likely,
    media_should_be_shown,
    media_story_key,
)


class BemobiNewsQualityTest(unittest.TestCase):
    def test_search_result_must_explicitly_mention_bemobi(self) -> None:
        self.assertFalse(
            media_is_relevant(
                "This is the most important part of the history of the world.",
                "The Salta Group owns 243 schools across the country.",
            )
        )

    def test_disclaimer_page_is_not_news(self) -> None:
        self.assertFalse(
            media_is_relevant(
                "This information is not an investment recommendation.",
                "Bemobi Mobile Tech S.A. develops digital payment solutions.",
            )
        )

    def test_realtime_quote_page_is_not_news(self) -> None:
        self.assertFalse(
            media_is_relevant(
                "BMOB3 Real-Time Graph - Bemobi Ações ON",
                "Track Bemobi quotes over the last three hours.",
            )
        )

    def test_ordinary_relevant_media_starts_low(self) -> None:
        self.assertTrue(
            media_is_relevant(
                "Bemobi expands presence in Latin America",
                "Executives discuss the company's strategy.",
            )
        )
        self.assertEqual(
            classify_media_item("Bemobi expands presence in Latin America"),
            ("OTHER", "NONE"),
        )

    def test_material_media_is_promoted(self) -> None:
        self.assertEqual(
            classify_media_item("Bemobi reports higher lucro and receita in 2Q26"),
            ("RESULTS", "POTENTIAL"),
        )
        self.assertEqual(
            classify_media_item("Bemobi announces parceria with telecom operator"),
            ("CORPORATE", "POTENTIAL"),
        )

    def test_generic_paywalled_mention_is_hidden(self) -> None:
        self.assertTrue(media_paywall_likely("O GLOBO"))
        self.assertFalse(
            media_should_be_shown(
                title="Bemobi CEO comments on technology trends",
                summary="Pedro Ripper spoke at an industry event.",
                publisher="O GLOBO",
            )
        )

    def test_material_paywalled_story_is_kept(self) -> None:
        self.assertTrue(
            media_should_be_shown(
                title="Bemobi lucro rises after strong quarterly resultado",
                summary="BMOB3 reported its latest numbers.",
                publisher="O GLOBO",
            )
        )

    def test_story_key_deduplicates_headline_formatting_on_same_day(self) -> None:
        first = media_story_key("Bemobi: lucro sobe 20%", "2026-09-05T10:00:00Z")
        second = media_story_key("BEMOBI - lucro sobe 20%", "2026-09-05T14:00:00Z")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

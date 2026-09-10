from __future__ import annotations

import sys
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from news_events import _company_name, _news_item, news_and_events  # noqa: E402


class CompanyNameTest(unittest.TestCase):
    def test_returns_names_for_companies_shown_in_dashboard(self) -> None:
        self.assertEqual(_company_name("OTEC"), "Otello")
        self.assertEqual(_company_name("BMOB3"), "Bemobi")

    def test_rejects_companies_outside_dashboard(self) -> None:
        self.assertIsNone(_company_name("LIF"))
        self.assertIsNone(_company_name(None))

    def test_ready_translation_is_exposed_but_original_is_preserved(self) -> None:
        item = _news_item(
            {
                "id": 7,
                "symbol": "BMOB3",
                "headline": "Ata",
                "category": "OTHER",
                "nav_impact": "NONE",
                "processing_status": "PARSED",
                "url": "https://cvm.example/original.pdf",
                "translation_status": "READY",
                "summary_status": "READY",
                "norwegian_title": "Styreprotokoll",
                "norwegian_summary": "Kort fortalt: Ingen materiell endring.",
                "translated_pdf_key": f"translated/bemobi/{'a' * 64}/bemobi-norsk.pdf",
            }
        )
        self.assertEqual(item["headline"], "Styreprotokoll")
        self.assertEqual(item["original_url"], "https://cvm.example/original.pdf")
        self.assertEqual(item["translated_pdf_url"], "/api/bemobi-translations/7.pdf")

    def test_processing_or_failed_translation_never_gets_pdf_link(self) -> None:
        for status in ("PROCESSING", "FAILED"):
            item = _news_item(
                {
                    "id": 8,
                    "symbol": "BMOB3",
                    "headline": "Ata",
                    "category": "OTHER",
                    "nav_impact": "NONE",
                    "processing_status": "PARSED",
                    "url": "https://cvm.example/original.pdf",
                    "translation_status": status,
                    "translated_pdf_key": f"translated/bemobi/{'a' * 64}/bemobi-norsk.pdf",
                }
            )
            self.assertIsNone(item["translated_pdf_url"])
            self.assertEqual(item["original_url"], "https://cvm.example/original.pdf")


class FakeNewsRepository:
    def __init__(self) -> None:
        self.news_offsets: list[int] = []

    async def all(
        self, query: str, parameters: tuple[object, ...]
    ) -> list[dict[str, object]]:
        if "FROM company_news" in query:
            assert "s.code IN ('NEWSWEB', 'CVM', 'BEMOBI_IR')" in query
            batch_size, offset = parameters
            assert isinstance(batch_size, int)
            assert isinstance(offset, int)
            self.news_offsets.append(offset)
            if offset == 0:
                return [
                    {
                        "metadata_json": '{"is_latest_version": false}',
                    }
                    for _ in range(batch_size)
                ]
            return [
                {
                    "id": 42,
                    "headline": "Ny, gjeldende melding",
                    "published_at": "2026-08-29T08:00:00Z",
                    "category": "OTHER",
                    "nav_impact": "NONE",
                    "summary": "Sammendrag",
                    "symbol": "OTEC",
                    "url": "https://example.com/news",
                    "source_code": "TEST",
                    "source_name": "Testkilde",
                    "metadata_json": '{"is_latest_version": true}',
                }
            ]
        return []

    async def first(
        self, query: str, parameters: tuple[object, ...] = ()
    ) -> dict[str, object] | None:
        return None


class NewsPaginationTest(unittest.IsolatedAsyncioTestCase):
    async def test_finds_current_news_after_many_outdated_versions(self) -> None:
        repository = FakeNewsRepository()

        result = await news_and_events(
            repository,
            as_of_date="2026-08-29",
            news_limit=1,
        )

        self.assertEqual(repository.news_offsets, [0, 3])
        self.assertEqual([item["id"] for item in result["news"]], [42])


if __name__ == "__main__":
    unittest.main()

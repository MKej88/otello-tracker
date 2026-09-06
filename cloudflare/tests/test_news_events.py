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


class MediaNewsItemTest(unittest.TestCase):
    def test_generic_media_is_reclassified_as_low_importance(self) -> None:
        item = _news_item(
            {
                "id": 7,
                "headline": "Bemobi expands in Latin America",
                "published_at": "2026-09-05T10:00:00Z",
                "category": "OTHER",
                "nav_impact": "POTENTIAL",
                "summary": "Executives discuss strategy.",
                "symbol": "BMOB3",
                "url": "https://example.com",
                "source_code": "BRAZIL_MEDIA",
                "source_name": "Brasiliansk medieomtale",
                "metadata_json": (
                    '{"content_type":"MEDIA","publisher":"InfoMoney",'
                    '"original_title":"Bemobi expands in Latin America",'
                    '"original_summary":"Executives discuss strategy."}'
                ),
            }
        )

        self.assertEqual(item["category"], "OTHER")
        self.assertEqual(item["nav_impact"], "NONE")
        self.assertEqual(item["importance"], "LOW")
        self.assertFalse(item["paywall_likely"])

    def test_material_paywalled_media_is_marked(self) -> None:
        item = _news_item(
            {
                "id": 8,
                "headline": "Bemobi profit rises",
                "published_at": "2026-09-05T11:00:00Z",
                "category": "OTHER",
                "nav_impact": "POTENTIAL",
                "summary": "Quarterly numbers improved.",
                "symbol": "BMOB3",
                "url": "https://example.com",
                "source_code": "BRAZIL_MEDIA",
                "source_name": "Brasiliansk medieomtale",
                "metadata_json": (
                    '{"content_type":"MEDIA","publisher":"O GLOBO",'
                    '"original_title":"Bemobi lucro rises after resultado",'
                    '"original_summary":"BMOB3 quarterly numbers improved."}'
                ),
            }
        )

        self.assertEqual(item["category"], "RESULTS")
        self.assertEqual(item["importance"], "HIGH")
        self.assertTrue(item["paywall_likely"])


class FakeNewsRepository:
    def __init__(self) -> None:
        self.news_offsets: list[int] = []

    async def all(
        self, query: str, parameters: tuple[object, ...]
    ) -> list[dict[str, object]]:
        if "FROM company_news" in query:
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
        if "FROM job_runs" in query:
            self.assert_media_status_parameters(parameters)
        return None

    def assert_media_status_parameters(self, parameters: tuple[object, ...]) -> None:
        assert parameters == ("bemobi_media_refresh",)


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
        self.assertEqual(
            result["media_status"],
            {"available": False, "status": None, "window_days": 30},
        )


if __name__ == "__main__":
    unittest.main()

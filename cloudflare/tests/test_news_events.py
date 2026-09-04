from __future__ import annotations

import sys
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from news_events import _company_name, news_and_events  # noqa: E402


class CompanyNameTest(unittest.TestCase):
    def test_returns_names_for_companies_shown_in_dashboard(self) -> None:
        self.assertEqual(_company_name("OTEC"), "Otello")
        self.assertEqual(_company_name("BMOB3"), "Bemobi")

    def test_rejects_companies_outside_dashboard(self) -> None:
        self.assertIsNone(_company_name("LIF"))
        self.assertIsNone(_company_name(None))


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

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "cloudflare" / "src" / "bemobi_source_status.py"
SPEC = importlib.util.spec_from_file_location(
    "worker_bemobi_source_status", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
worker_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker_module
SPEC.loader.exec_module(worker_module)
_operational_source_items = worker_module._operational_source_items
bemobi_source_status = worker_module.bemobi_source_status


class _CountingRepository:
    def __init__(self) -> None:
        self.queries = 0

    async def all(self, sql: str, parameters: tuple[str, ...] = ()) -> list[dict]:
        self.queries += 1
        assert "WHERE s.code IN" in sql
        assert len(parameters) == 7
        return [
            {
                "code": "B3",
                "base_url": "https://b3.example",
                "checked_at": "2026-09-07T08:00:00Z",
                "status": "OK",
                "error_message": None,
                "fetched_at": "2026-09-07T08:00:00Z",
                "published_at": "2026-09-06",
            }
        ]


def test_operational_sources_are_loaded_in_one_query() -> None:
    repository = _CountingRepository()

    items = asyncio.run(_operational_source_items(repository))

    assert repository.queries == 1
    assert len(items) == 7
    assert [item["key"] for item in items] == [
        "norges_bank",
        "b3",
        "euronext",
        "yahoo_finance",
        "newsweb",
        "otello_ir",
        "life360_ir",
    ]
    b3 = next(item for item in items if item["key"] == "b3")
    assert b3["status"] == "OK"
    assert b3["url"] == "https://b3.example"


class _SourceStatusRepository:
    def __init__(self) -> None:
        self.fact_parameters: list[tuple[str, ...]] = []

    async def first(
        self,
        sql: str,
        parameters: tuple[str, ...] = (),
    ) -> dict | None:
        if "FROM source_health" in sql:
            return None
        self.fact_parameters.append(parameters)
        return None

    async def all(self, sql: str, parameters: tuple[str, ...]) -> list[dict]:
        return []


def test_investor_sources_keep_definition_order_queries_and_labels() -> None:
    repository = _SourceStatusRepository()

    result = asyncio.run(bemobi_source_status(repository))

    investor_items = result["items"][-4:]
    assert [item["key"] for item in investor_items] == [
        "ir",
        "result_release",
        "consensus",
        "xp_preview",
    ]
    assert [item["label"] for item in investor_items] == [
        "Eierandel og analytikerdekning",
        "Resultater",
        "Årsestimater / meglermodeller",
        "Forhåndsestimat neste kvartal",
    ]
    assert [item["source"] for item in investor_items] == [
        "Bemobi IR",
        "CVM / Bemobi",
        "Offentlige meglerhus",
        "XP",
    ]
    assert repository.fact_parameters == [
        ("OWNERSHIP", "ANALYST"),
        ("RESULT",),
        ("FORWARD_CONSENSUS",),
        ("NEXT_QUARTER", "XP"),
    ]

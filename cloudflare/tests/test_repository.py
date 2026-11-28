from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from src.repository import D1Repository, D1WriteRepository
from src.performance_repository import PerformanceD1Repository, PerformanceD1WriteRepository


@dataclass
class QueryResult:
    results: Any


class Statement:
    def __init__(self, result: object) -> None:
        self.result = result

    async def all(self) -> object:
        return self.result

    def bind(self, *parameters: object) -> Statement:
        self.parameters = parameters
        return self


class Database:
    def __init__(self, result: object) -> None:
        self.result = result

    def prepare(self, _sql: str) -> Statement:
        return Statement(self.result)


class BatchDatabase(Database):
    def __init__(self) -> None:
        super().__init__(QueryResult(results=[]))
        self.statements: list[Statement] = []

    async def batch(self, statements: list[Statement]) -> list[object]:
        self.statements = statements
        return []


class MutableBatchDatabase(BatchDatabase):
    async def batch(self, statements: list[Statement]) -> list[object]:
        result = await super().batch(statements)
        self.result = QueryResult(results=[{"value": "oppdatert"}])
        return result


def test_all_accepts_an_empty_result_list() -> None:
    repository = D1Repository(Database(QueryResult(results=[])))

    assert asyncio.run(repository.all("SELECT 1")) == []


@pytest.mark.parametrize("result", [object(), QueryResult(results=None)])
def test_all_rejects_a_missing_or_null_results_field(result: object) -> None:
    repository = D1Repository(Database(result))

    with pytest.raises(RuntimeError, match="results"):
        asyncio.run(repository.all("SELECT 1"))


def test_all_rejects_non_object_rows() -> None:
    repository = D1Repository(Database(QueryResult(results=[{"id": 1}, None])))

    with pytest.raises(RuntimeError, match="rad som ikke er et objekt"):
        asyncio.run(repository.all("SELECT 1"))


def test_run_batch_prepares_all_writes_for_one_database_call() -> None:
    database = BatchDatabase()
    repository = D1WriteRepository(database)

    asyncio.run(
        repository.run_batch(
            [
                ("UPDATE example SET value=? WHERE id=?", ("a", 1)),
                ("DELETE FROM example WHERE id=?", (2,)),
            ]
        )
    )

    assert len(database.statements) == 2
    assert database.statements[0].parameters == ("a", 1)
    assert database.statements[1].parameters == (2,)


def test_performance_repository_invalidates_read_cache_after_batch() -> None:
    database = MutableBatchDatabase()
    repository = PerformanceD1WriteRepository(database)

    assert asyncio.run(repository.all("SELECT value FROM example")) == []
    asyncio.run(
        repository.run_batch(
            [("INSERT INTO example(value) VALUES (?)", ("oppdatert",))]
        )
    )

    assert asyncio.run(repository.all("SELECT value FROM example")) == [
        {"value": "oppdatert"}
    ]
    assert repository.performance_metrics()["d1_writes"] == 1


def test_row_metrics_count_scanned_rows_not_result_length_and_do_not_count_cache_hits():
    from types import SimpleNamespace

    result = SimpleNamespace(results=[{"id": 1}], meta={"rows_read": 200, "rows_written": 0})
    repository = PerformanceD1Repository(Database(result))

    async def read():
        assert await repository.all("SELECT id FROM example") == [{"id": 1}]
        assert await repository.all("SELECT id FROM example") == [{"id": 1}]
        await repository.all_uncached("SELECT id FROM example")

    asyncio.run(read())
    metrics = repository.performance_metrics()
    assert metrics["d1_operations"] == 2
    assert metrics["d1_row_meta_operations"] == 2
    assert metrics["d1_rows_read"] == 400
    assert metrics["d1_rows_written"] == 0


@pytest.mark.parametrize("meta", [None, {"rows_read": 2}, {"rows_read": -1, "rows_written": 0},
                                {"rows_read": True, "rows_written": 0},
                                {"rows_read": float("nan"), "rows_written": 0}])
def test_invalid_row_metadata_is_unknown_not_zero(meta):
    from types import SimpleNamespace

    database = Database(SimpleNamespace(results=[], meta={"rows_read": 3, "rows_written": 0}))
    repository = PerformanceD1Repository(database)
    asyncio.run(repository.all("SELECT 1"))
    database.result = SimpleNamespace(results=[], meta=meta)
    asyncio.run(repository.all_uncached("SELECT 2"))
    metrics = repository.performance_metrics()
    assert metrics["d1_row_meta_operations"] == 1
    assert metrics["d1_rows_read_observed"] == 3
    assert metrics["d1_rows_read"] is None
    assert metrics["d1_rows_written"] is None


def test_write_and_batch_row_counts_are_per_statement():
    from types import SimpleNamespace

    class WriteStatement(Statement):
        async def run(self):
            return self.result

    class CostDatabase(Database):
        def prepare(self, sql):
            return WriteStatement(self.result)

        async def batch(self, statements):
            return [
                SimpleNamespace(meta={"rows_read": 5, "rows_written": 2}),
                SimpleNamespace(meta={"rows_read": 8.0, "rows_written": 3.0}),
            ]

    database = CostDatabase(SimpleNamespace(meta={"rows_read": 4, "rows_written": 1}))
    repository = PerformanceD1WriteRepository(database)
    asyncio.run(repository.run("UPDATE example SET value=1"))
    asyncio.run(repository.run_batch([("UPDATE example SET value=2", ()), ("DELETE FROM example", ())]))
    metrics = repository.performance_metrics()
    assert metrics["d1_operations"] == 3
    assert metrics["d1_row_meta_operations"] == 3
    assert metrics["d1_rows_read"] == 17
    assert metrics["d1_rows_written"] == 6

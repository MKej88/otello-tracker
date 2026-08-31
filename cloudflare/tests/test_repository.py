from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from src.repository import D1Repository, D1WriteRepository


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

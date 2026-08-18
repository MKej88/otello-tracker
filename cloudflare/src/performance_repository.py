from __future__ import annotations

from time import perf_counter
from typing import Any

try:
    from .repository import D1Repository, D1WriteRepository
except ImportError:
    from repository import D1Repository, D1WriteRepository

READ_CACHE_LIMIT = 256


def _cacheable(sql: str) -> bool:
    prefix = sql.lstrip().upper()
    return prefix.startswith("SELECT") or prefix.startswith("WITH")


def _clone_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


class _PerformanceState:
    def _init_performance_state(self) -> None:
        self._read_cache: dict[tuple[str, tuple[Any, ...]], list[dict[str, Any]]] = {}
        self._source_ids: dict[str, int] = {}
        self._instrument_ids: dict[str, int] = {}
        self._read_queries = 0
        self._write_queries = 0
        self._cache_hits = 0
        self._read_ms = 0.0
        self._write_ms = 0.0

    def _cache_key(
        self,
        sql: str,
        parameters: tuple[Any, ...],
    ) -> tuple[str, tuple[Any, ...]] | None:
        if not _cacheable(sql):
            return None
        try:
            hash(parameters)
        except TypeError:
            return None
        return sql, parameters

    def _remember(
        self,
        key: tuple[str, tuple[Any, ...]] | None,
        rows: list[dict[str, Any]],
    ) -> None:
        if key is None:
            return
        if len(self._read_cache) >= READ_CACHE_LIMIT:
            self._read_cache.clear()
        self._read_cache[key] = _clone_rows(rows)

    def _record_uncached_read(self, started: float) -> None:
        self._read_ms += (perf_counter() - started) * 1000
        self._read_queries += 1

    def performance_metrics(self) -> dict[str, Any]:
        return {
            "d1_reads": self._read_queries,
            "d1_writes": self._write_queries,
            "d1_operations": self._read_queries + self._write_queries,
            "read_cache_hits": self._cache_hits,
            "read_cache_entries": len(self._read_cache),
            "source_id_cache_entries": len(self._source_ids),
            "instrument_id_cache_entries": len(self._instrument_ids),
            "d1_read_ms": round(self._read_ms, 2),
            "d1_write_ms": round(self._write_ms, 2),
        }


class PerformanceD1Repository(_PerformanceState, D1Repository):
    """Request-scoped D1 reader with exact-query memoization and lightweight metrics."""

    def __init__(self, database: Any):
        super().__init__(database)
        self._init_performance_state()

    async def all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        key = self._cache_key(sql, parameters)
        if key is not None and key in self._read_cache:
            self._cache_hits += 1
            return _clone_rows(self._read_cache[key])

        started = perf_counter()
        rows = await super().all(sql, parameters)
        self._read_ms += (perf_counter() - started) * 1000
        self._read_queries += 1
        self._remember(key, rows)
        return rows

    async def all_uncached(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        started = perf_counter()
        rows = await D1Repository.all(self, sql, parameters)
        self._record_uncached_read(started)
        return rows


class PerformanceD1WriteRepository(_PerformanceState, D1WriteRepository):
    """Scheduled-ingestion repository that minimizes repeated D1 round trips.

    The general SELECT cache is invalidated after every write, while source/instrument
    IDs stay cached because reference rows are immutable during a Worker invocation.
    Large sequential audit exports can explicitly use ``all_uncached`` so those pages do
    not accumulate inside the request-scoped memoization cache.
    """

    def __init__(self, database: Any):
        super().__init__(database)
        self._init_performance_state()

    async def all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        key = self._cache_key(sql, parameters)
        if key is not None and key in self._read_cache:
            self._cache_hits += 1
            return _clone_rows(self._read_cache[key])

        started = perf_counter()
        rows = await super().all(sql, parameters)
        self._read_ms += (perf_counter() - started) * 1000
        self._read_queries += 1
        self._remember(key, rows)
        return rows

    async def all_uncached(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        started = perf_counter()
        rows = await D1Repository.all(self, sql, parameters)
        self._record_uncached_read(started)
        return rows

    async def run(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        started = perf_counter()
        result = await super().run(sql, parameters)
        self._write_ms += (perf_counter() - started) * 1000
        self._write_queries += 1
        self._read_cache.clear()
        return result

    async def source_id(self, code: str) -> int:
        cached = self._source_ids.get(code)
        if cached is not None:
            self._cache_hits += 1
            return cached
        value = await super().source_id(code)
        self._source_ids[code] = value
        return value

    async def instrument_id(self, symbol: str) -> int:
        cached = self._instrument_ids.get(symbol)
        if cached is not None:
            self._cache_hits += 1
            return cached
        value = await super().instrument_id(symbol)
        self._instrument_ids[symbol] = value
        return value

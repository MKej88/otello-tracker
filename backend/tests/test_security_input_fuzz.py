"""Deterministic adversarial-input regression tests for public APIs and Worker size limits.

The corpus is seeded for repeatable CI failures. No HTTP calls leave the process,
no external database is accessed, and no new production dependencies are required.
These are targeted fuzz-style tests, not an OSS-Fuzz integration.
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app

CLOUDFLARE_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from bounded_response import read_response_bytes  # noqa: E402


class _ChunkReader:
    def __init__(self, chunks: list[bytes | bytearray | memoryview]) -> None:
        self._chunks = iter(chunks)
        self.cancel_reason: str | None = None
        self.released = False

    async def read(self) -> SimpleNamespace:
        try:
            return SimpleNamespace(done=False, value=next(self._chunks))
        except StopIteration:
            return SimpleNamespace(done=True, value=None)

    async def cancel(self, reason: str) -> None:
        self.cancel_reason = reason

    def releaseLock(self) -> None:  # noqa: N802 - browser Fetch API spelling
        self.released = True


def _response(reader: _ChunkReader, declared: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        body=SimpleNamespace(getReader=lambda: reader),
        headers={} if declared is None else {"content-length": declared},
    )


@pytest.mark.parametrize(
    ("endpoint", "key", "minimum", "maximum"),
    [
        ("/api/bemobi/news", "limit", 1, 200),
        ("/api/news-events", "limit", 1, 100),
        ("/api/dashboard/history", "days", 7, 3650),
        ("/api/dashboard/history", "max_points", 50, 1000),
        ("/api/dashboard/discount-history", "days", 30, 3650),
        ("/api/dashboard/discount-history", "max_points", 50, 1000),
    ],
)
def test_api_rejects_out_of_range_or_malformed_numbers(
    endpoint: str, key: str, minimum: int, maximum: int
) -> None:
    rng = random.Random(0x07110 + minimum + maximum)
    values = [
        str(minimum - 1),
        str(maximum + 1),
        "-999999999999999999999",
        "999999999999999999999",
        "1.25",
        "NaN",
        "Infinity",
        "true",
        "null",
        "<script>alert(1)</script>",
        "7" * 150,
    ]
    values.extend(str(-rng.randint(1, 100_000)) for _ in range(12))
    values.extend(str(maximum + rng.randint(1, 100_000)) for _ in range(12))

    # Without a context manager, TestClient does not run the DB-seeding lifespan.
    # FastAPI must reject these values before invoking any database handler.
    client = TestClient(app)
    try:
        for value in values:
            result = client.get(endpoint, params={key: value})
            assert result.status_code == 422, (endpoint, key, value, result.status_code)
    finally:
        client.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/buybacks/forecast",
        "/api/buybacks/dashboard",
        "/api/buybacks/overview-status",
        "/api/news-events",
    ],
)
def test_api_rejects_malformed_calendar_dates(endpoint: str) -> None:
    invalid = [
        "2026-02-29",
        "2026-02-30",
        "2026-00-01",
        "2026-13-01",
        "2026-01-00",
        "2026/10/11",
        "not-a-date",
        "9999-99-99",
        "<script>alert(1)</script>",
        "2" * 150,
    ]
    client = TestClient(app)
    try:
        for value in invalid:
            result = client.get(endpoint, params={"as_of_date": value})
            assert result.status_code == 422, (endpoint, value, result.status_code)
    finally:
        client.close()


def test_worker_response_size_limit_with_adversarial_chunk_boundaries() -> None:
    rng = random.Random(0x0E710)
    for _ in range(160):
        max_bytes = rng.randint(1, 4096)
        chunk_count = rng.randint(0, 25)
        data = [rng.randbytes(rng.randint(0, 480)) for _ in range(chunk_count)]
        types = (bytes, bytearray, memoryview)
        mixed = [types[rng.randrange(3)](chunk) for chunk in data]
        expected = b"".join(data)
        reader = _ChunkReader(mixed)

        if len(expected) > max_bytes:
            with pytest.raises(ValueError, match="overstiger Worker-grensen"):
                asyncio.run(
                    read_response_bytes(
                        _response(reader), max_bytes=max_bytes, label="upstream"
                    )
                )
            assert reader.cancel_reason == "response too large"
        else:
            received = asyncio.run(
                read_response_bytes(
                    _response(reader), max_bytes=max_bytes, label="upstream"
                )
            )
            assert received == expected
            assert reader.cancel_reason is None
        assert reader.released


@pytest.mark.parametrize("length", ["-1", "NaN", "3.14", "0x10", "x" * 100])
def test_worker_rejects_invalid_content_length_before_reading(length: str) -> None:
    reader = _ChunkReader([b"safe"])
    with pytest.raises(ValueError, match="Ugyldig Content-Length"):
        asyncio.run(
            read_response_bytes(
                _response(reader, declared=length), max_bytes=100, label="upstream"
            )
        )
    # Declared-length validation happens before acquiring or reading a stream.
    assert reader.released is False


def test_worker_rejects_declared_oversize_before_reading() -> None:
    reader = _ChunkReader([b"small"])
    with pytest.raises(ValueError, match="overstiger Worker-grensen"):
        asyncio.run(
            read_response_bytes(
                _response(reader, declared="1000000"),
                max_bytes=1024,
                label="upstream",
            )
        )
    assert reader.released is False

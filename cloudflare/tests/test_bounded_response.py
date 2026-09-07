from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from bounded_response import read_response_bytes  # noqa: E402


class StreamReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = iter(chunks)
        self.cancel_reason: str | None = None
        self.lock_released = False

    async def read(self) -> SimpleNamespace:
        try:
            return SimpleNamespace(done=False, value=next(self.chunks))
        except StopIteration:
            return SimpleNamespace(done=True, value=None)

    async def cancel(self, reason: str) -> None:
        self.cancel_reason = reason

    def releaseLock(self) -> None:  # noqa: N802 - Fetch API method name
        self.lock_released = True


def _streaming_response(reader: StreamReader) -> SimpleNamespace:
    body = SimpleNamespace(getReader=lambda: reader)
    return SimpleNamespace(body=body, headers={})


def test_rejects_declared_oversized_response_before_reading_body() -> None:
    body_read = False

    async def array_buffer() -> bytes:
        nonlocal body_read
        body_read = True
        return b"data"

    response = SimpleNamespace(
        headers={"content-length": "11"},
        arrayBuffer=array_buffer,
    )

    with pytest.raises(ValueError, match="overstiger Worker-grensen"):
        asyncio.run(
            read_response_bytes(response, max_bytes=10, label="ekstern respons")
        )

    assert body_read is False


def test_cancels_chunked_response_when_combined_payload_exceeds_limit() -> None:
    reader = StreamReader([b"123456", b"78901"])

    with pytest.raises(ValueError, match="overstiger Worker-grensen"):
        asyncio.run(
            read_response_bytes(
                _streaming_response(reader),
                max_bytes=10,
                label="ekstern respons",
            )
        )

    assert reader.cancel_reason == "response too large"
    assert reader.lock_released is True


def test_accepts_chunked_response_exactly_at_size_limit() -> None:
    reader = StreamReader([b"1234", b"567890"])

    payload = asyncio.run(
        read_response_bytes(
            _streaming_response(reader),
            max_bytes=10,
            label="ekstern respons",
        )
    )

    assert payload == b"1234567890"
    assert reader.cancel_reason is None
    assert reader.lock_released is True

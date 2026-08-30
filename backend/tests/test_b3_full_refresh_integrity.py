from __future__ import annotations

import asyncio
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from b3_full_refresh import refresh_bmob3_close  # noqa: E402


def _b3_line(*, trading_date: str) -> str:
    chars = [" "] * 245

    def put(start: int, end: int, value: str) -> None:
        chars[start:end] = list(value.ljust(end - start)[: end - start])

    put(0, 2, "01")
    put(2, 10, trading_date)
    put(10, 12, "02")
    put(12, 24, "BMOB3")
    put(24, 27, "010")
    put(108, 121, "0000000002281")
    put(210, 217, "0000001")
    return "".join(chars)


def _zip_payload(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("COTAHIST_D17082026.TXT", text.encode("latin-1"))
    return buffer.getvalue()


class _Response:
    status = 200
    ok = True

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def arrayBuffer(self) -> bytes:  # noqa: N802
        return self._payload


def test_b3_refresh_rejects_payload_for_a_different_trading_date() -> None:
    class Repository:
        async def create_source_document(self, **kwargs):
            raise AssertionError("feildatert dokument skal ikke lagres")

        async def upsert_market_price(self, **kwargs):
            raise AssertionError("feildatert kurs skal ikke lagres")

    async def fetcher(url, **kwargs):
        return _Response(_zip_payload(_b3_line(trading_date="20260814") + "\n"))

    with pytest.raises(ValueError, match="forventet 2026-08-17, fant 2026-08-14"):
        asyncio.run(
            refresh_bmob3_close(
                Repository(),
                target_date="2026-08-17",
                max_lookback_days=0,
                fetcher=fetcher,
            )
        )

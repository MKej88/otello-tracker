import asyncio
from pathlib import Path

import pytest

from cloudflare.src.quote_details import _volume_stats

ROOT = Path(__file__).resolve().parents[2]


class _BrokenRepository:
    async def all(self, *_args, **_kwargs):
        raise RuntimeError("D1 unavailable")


def test_worker_otec_volume_database_failure_is_propagated() -> None:
    with pytest.raises(RuntimeError, match="D1 unavailable"):
        asyncio.run(_volume_stats(_BrokenRepository(), "OTEC", []))


def test_issue_83_market_quote_contract() -> None:
    backend = (ROOT / "backend/app/marketdata/quote_details.py").read_text(
        encoding="utf-8"
    )
    worker = (ROOT / "cloudflare/src/quote_details.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/MarketQuotePanel.tsx").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    for source in (backend, worker):
        assert '"last_updated_at"' in source
        assert '"last_close"' in source
        assert '"average_3m"' in source
        assert '"latest_above_average"' in source
        assert '"range_52w"' in source
        assert '"open"' in source
        assert '"low"' in source
        assert '"high"' in source

    for label in (
        "Sist oppdatert",
        "52-ukers lav / høy",
        "3 mnd snittvolum",
        "Høyere enn 3 mnd snitt",
        "Siste volum",
        "Åpning",
        "Dagens lav",
        "Dagens høy",
        "Siste sluttkurs",
    ):
        assert label in frontend

    assert "/api/market/quotes" in ci
    assert "worker-quotes.json" in ci

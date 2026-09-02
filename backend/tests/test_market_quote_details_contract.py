import asyncio
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKER_QUOTE_DETAILS = ROOT / "cloudflare/src/quote_details.py"


def _load_worker_volume_stats():
    spec = importlib.util.spec_from_file_location(
        "worker_quote_details", WORKER_QUOTE_DETAILS
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._volume_stats


class _BrokenRepository:
    async def all(self, *_args, **_kwargs):
        raise RuntimeError("D1 unavailable")


def test_worker_otec_volume_database_failure_is_propagated() -> None:
    with pytest.raises(RuntimeError, match="D1 unavailable"):
        asyncio.run(_load_worker_volume_stats()(_BrokenRepository(), "OTEC", []))


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
        assert '"changes"' in source
        assert '"relative_3m"' in source
        assert '"open"' in source
        assert '"low"' in source
        assert '"high"' in source

    for label in (
        "52 uker",
        "1 mnd",
        "3 mnd",
        "NAV / aksje",
        "Volum vs 3 mnd",
        "NAV-effekt 1 mnd",
        "Verdi for Otello",
    ):
        assert label in frontend

    assert "/api/market/quotes" in ci
    assert "worker-quotes.json" in ci

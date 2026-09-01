from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKER_QUOTE_DETAILS = ROOT / "cloudflare" / "src" / "quote_details.py"
SCHEDULED = ROOT / "cloudflare" / "src" / "scheduled.py"


def _load_worker_quote_details():
    spec = importlib.util.spec_from_file_location("worker_quote_details_lif_test", WORKER_QUOTE_DETAILS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lif_yahoo_daily_bar_is_intraday_during_nasdaq_session() -> None:
    module = _load_worker_quote_details()
    price_type, observed_at = module._lif_display_state(
        {
            "trading_date": "2026-08-31",
            "price_type": "CLOSE",
            "observed_at": "2026-08-31T13:30:00Z",
            "source_retrieved_at": "2026-08-31T18:00:00Z",
        }
    )

    assert price_type == "LAST"
    assert observed_at == "2026-08-31T18:00:00Z"


def test_lif_completed_bar_uses_real_nasdaq_close_timestamp() -> None:
    module = _load_worker_quote_details()
    price_type, observed_at = module._lif_display_state(
        {
            "trading_date": "2026-08-31",
            "price_type": "CLOSE",
            "observed_at": "2026-08-31T13:30:00Z",
            "source_retrieved_at": "2026-09-01T08:00:00Z",
        }
    )

    assert price_type == "CLOSE"
    # 16:00 New York = 20:00 UTC = 22:00 Europe/Oslo on 31 August 2026.
    assert observed_at == "2026-08-31T20:00:00Z"


def test_lif_close_timestamp_handles_dst() -> None:
    module = _load_worker_quote_details()
    assert module._nasdaq_close_timestamp("2026-12-01") == "2026-12-01T21:00:00Z"


def test_lif_refresh_is_already_on_the_30_minute_cron() -> None:
    source = SCHEDULED.read_text(encoding="utf-8")
    assert 'FAST_REFRESH_CRON = "*/30 * * * *"' in source
    assert '"life360_lif_repair"' in source
    assert "force_refresh=True" in source

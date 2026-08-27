from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app/db/migrations/0028_life360_price_backfill.sql"
D1 = ROOT / "cloudflare/migrations/0020_life360_price_backfill.sql"
EXPECTED = {
    "2026-07-27": "53.83",
    "2026-07-28": "56.68",
    "2026-07-29": "55.29",
    "2026-07-30": "55.68",
    "2026-07-31": "54.05",
}


def test_life360_price_backfill_is_source_backed_and_parity_matched() -> None:
    backend = BACKEND.read_text()
    d1 = D1.read_text()
    assert backend == d1
    assert "FINANCECHARTS" in d1
    assert "financecharts.com/stocks/LIF/summary/price" in d1
    assert "stockanalysis.com/stocks/lif/history/" in d1
    assert "RECONSTRUCTED" in d1
    assert "mp.trading_date < '2026-07-27'" in d1
    for trading_date, close in EXPECTED.items():
        assert trading_date in d1
        assert f"'{close}'" in d1


def test_life360_price_backfill_is_idempotent_by_source_and_day() -> None:
    sql = D1.read_text()
    assert sql.count("SELECT 1 FROM market_prices existing") == len(EXPECTED)
    assert "existing.source_id=s.id" in sql
    assert "existing.price_type='CLOSE'" in sql

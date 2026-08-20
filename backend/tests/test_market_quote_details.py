from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.buybacks.activity import seed_otec_activity_history
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import upsert_market_price
from app.marketdata.b3_cotahist import parse_cotahist_line
from app.marketdata.quote_details import market_quote_details


ROOT = Path(__file__).resolve().parents[2]


def _put(chars: list[str], start: int, end: int, value: str) -> None:
    chars[start:end] = list(value.rjust(end - start)[: end - start])


def _cotahist_line() -> str:
    chars = list(" " * 245)
    chars[0:2] = list("01")
    chars[2:10] = list("20260819")
    chars[10:12] = list("02")
    chars[12:24] = list("BMOB3".ljust(12))
    chars[24:27] = list("010")
    chars[52:56] = list("R$  ")
    _put(chars, 56, 69, "0000000002250")
    _put(chars, 69, 82, "0000000002310")
    _put(chars, 82, 95, "0000000002210")
    _put(chars, 95, 108, "0000000002270")
    _put(chars, 108, 121, "0000000002290")
    _put(chars, 147, 152, "00421")
    _put(chars, 152, 170, "000000000001234567")
    _put(chars, 170, 188, "000000002801234500")
    _put(chars, 210, 217, "0000001")
    chars[230:242] = list("BRBMOBACNOR1")
    return "".join(chars)


def test_cotahist_parser_exposes_ohlc_and_share_quantity() -> None:
    row = parse_cotahist_line(_cotahist_line())
    assert row is not None
    assert row.open == Decimal("22.5")
    assert row.high == Decimal("23.1")
    assert row.low == Decimal("22.1")
    assert row.average == Decimal("22.7")
    assert row.close == Decimal("22.9")
    assert row.trades == 421
    assert row.quantity == 1_234_567


def _seed_prices(database: str) -> None:
    with get_connection(database) as connection:
        for day, close, volume, low, high in (
            ("2026-08-17", "22.10", 110000, "21.80", "22.40"),
            ("2026-08-18", "22.40", 120000, "22.00", "22.70"),
            ("2026-08-19", "22.90", 130000, "22.10", "23.10"),
        ):
            upsert_market_price(
                connection,
                symbol="BMOB3",
                observed_at=f"{day}T23:59:59Z",
                trading_date=day,
                price_type="CLOSE",
                price=close,
                currency="BRL",
                source_code="B3",
                quality="DIRECT",
                metadata={
                    "open": "22.50",
                    "low": low,
                    "high": high,
                    "volume_shares": volume,
                },
            )
        upsert_market_price(
            connection,
            symbol="BMOB3",
            observed_at="2026-08-20T13:45:00Z",
            trading_date="2026-08-20",
            price_type="LAST",
            price="23.20",
            currency="BRL",
            source_code="B3",
            quality="DIRECT",
            metadata={"open_price": "23.00", "min_price": "22.80", "max_price": "23.40"},
        )
        for day, close in (("2026-08-18", "18.00"), ("2026-08-19", "18.20")):
            upsert_market_price(
                connection,
                symbol="OTEC",
                observed_at=f"{day}T15:30:00Z",
                trading_date=day,
                price_type="CLOSE",
                price=close,
                currency="NOK",
                source_code="EURONEXT",
                quality="DIRECT",
            )
        for at, price in (
            ("2026-08-20T07:05:00Z", "18.30"),
            ("2026-08-20T08:30:00Z", "18.55"),
            ("2026-08-20T09:30:00Z", "18.40"),
        ):
            upsert_market_price(
                connection,
                symbol="OTEC",
                observed_at=at,
                trading_date="2026-08-20",
                price_type="LAST",
                price=price,
                currency="NOK",
                source_code="EURONEXT",
                quality="DIRECT",
            )
        connection.commit()


def test_market_quote_details_returns_issue_83_fields(tmp_path) -> None:
    database = str(tmp_path / "quote-details.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_prices(database)

    payload = market_quote_details(database)
    assert payload["ready"] is True

    bmob3 = payload["symbols"]["BMOB3"]
    assert bmob3["last"] == 23.2
    assert bmob3["last_updated_at"] == "2026-08-20T13:45:00Z"
    assert bmob3["session"] == {
        "open": 23.0,
        "low": 22.8,
        "high": 23.4,
        "basis": "EXCHANGE_SESSION_SUMMARY",
    }
    assert bmob3["last_close"]["price"] == 22.9
    assert bmob3["volume"]["latest"] == 130000.0
    assert bmob3["volume"]["average_sessions"] == 3
    assert bmob3["range_52w"]["low"] == 21.8
    assert bmob3["range_52w"]["high"] == 23.1

    otec = payload["symbols"]["OTEC"]
    assert otec["last"] == 18.4
    assert otec["session"]["open"] == 18.3
    assert otec["session"]["low"] == 18.3
    assert otec["session"]["high"] == 18.55
    assert otec["session"]["basis"] == "OBSERVED_TRADES"
    assert otec["last_close"]["price"] == 18.2
    assert otec["volume"]["latest"] is not None
    assert otec["volume"]["average_sessions"] == 20


def test_issue_83_is_exposed_in_backend_worker_and_frontend() -> None:
    backend = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare/src/app.py").read_text(encoding="utf-8")
    worker_service = (ROOT / "cloudflare/src/quote_details.py").read_text(encoding="utf-8")
    panel = (ROOT / "frontend/src/MarketQuotePanel.tsx").read_text(encoding="utf-8")
    economic = (ROOT / "frontend/src/EconomicNavPanel.tsx").read_text(encoding="utf-8")

    assert '@app.get("/api/market/quotes")' in backend
    assert '@app.get("/api/market/quotes")' in worker
    assert "market_quote_details" in worker_service
    for label in ("Sist oppdatert", "52-ukers lav / høy", "Snittvolum", "Siste volum", "Åpning", "Dagens lav", "Dagens høy", "Siste sluttkurs"):
        assert label in panel
    assert "<MarketQuotePanel />" in economic

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_issue_83_market_quote_contract() -> None:
    backend = (ROOT / "backend/app/marketdata/quote_details.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare/src/quote_details.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/MarketQuotePanel.tsx").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    for source in (backend, worker):
        assert '"last_updated_at"' in source
        assert '"last_close"' in source
        assert '"average_20d"' in source
        assert '"range_52w"' in source
        assert '"open"' in source
        assert '"low"' in source
        assert '"high"' in source

    for label in (
        "Sist oppdatert",
        "52-ukers lav / høy",
        "Snittvolum",
        "Siste volum",
        "Åpning",
        "Dagens lav",
        "Dagens høy",
        "Siste sluttkurs",
    ):
        assert label in frontend

    assert "/api/market/quotes" in ci
    assert "worker-quotes.json" in ci

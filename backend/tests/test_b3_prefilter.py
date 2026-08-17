from datetime import date
from http.client import IncompleteRead
from io import BytesIO
from urllib.error import HTTPError
from zipfile import ZIP_DEFLATED, ZipFile

import app.marketdata.b3_cotahist as b3
from app.marketdata.b3_cotahist import parse_cotahist_zip_bytes


def _put(chars: list[str], start: int, end: int, value: str) -> None:
    chars[start:end] = list(value.ljust(end - start)[: end - start])


def _line(ticker: str, factor: int, close_cents: int = 2271) -> str:
    chars = list(" " * 245)
    _put(chars, 0, 2, "01")
    _put(chars, 2, 10, "20251230")
    _put(chars, 10, 12, "02")
    _put(chars, 12, 24, ticker)
    _put(chars, 24, 27, "010")
    _put(chars, 52, 56, "R$")
    _put(chars, 108, 121, f"{close_cents:013d}")
    _put(chars, 147, 152, "00010")
    _put(chars, 170, 188, f"{100000:018d}")
    _put(chars, 210, 217, f"{factor:07d}")
    _put(chars, 230, 242, "BRBMOBACNOR1" if ticker == "BMOB3" else "BRTESTACNOR1")
    return "".join(chars)


def test_b3_zip_filters_ticker_before_validating_other_instruments() -> None:
    """An unrelated COTAHIST instrument may use another quotation factor."""
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "COTAHIST_A2025.TXT",
            "00HEADER\n"
            + _line("OTHER3", factor=100)
            + "\n"
            + _line("BMOB3", factor=1)
            + "\n99TRAILER\n",
        )

    prices = parse_cotahist_zip_bytes(output.getvalue(), "BMOB3")
    assert len(prices) == 1
    assert prices[0].ticker == "BMOB3"
    assert str(prices[0].close) == "22.71"
    assert prices[0].quotation_factor == 1


class _FakeResponse:
    def __init__(self, payload: bytes | Exception, headers=None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        if isinstance(self.payload, Exception):
            raise self.payload
        if size is None or size < 0:
            return self.payload
        return self.payload[:size]


def test_b3_download_retries_incomplete_transfer(monkeypatch) -> None:
    responses = iter(
        [
            _FakeResponse(IncompleteRead(b"partial", 100)),
            _FakeResponse(b"PKvalid-zip-placeholder"),
        ]
    )
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return next(responses)

    monkeypatch.setattr(b3, "urlopen", fake_urlopen)
    monkeypatch.setattr(b3.time, "sleep", lambda _: None)

    payload = b3.download_cotahist_year(2025, timeout=1, attempts=2)

    assert payload == b"PKvalid-zip-placeholder"
    assert len(calls) == 2


def test_daily_cotahist_404_is_normal_unavailable(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(b3, "urlopen", fake_urlopen)
    payload = b3.download_cotahist_day(date(2026, 8, 17), attempts=1)
    assert payload is None


def test_daily_cotahist_rejects_oversized_response(monkeypatch) -> None:
    response = _FakeResponse(
        b"PKtoo-big",
        headers={"Content-Length": str(b3.MAX_DAILY_ZIP_BYTES + 1)},
    )
    monkeypatch.setattr(b3, "urlopen", lambda *_args, **_kwargs: response)

    try:
        b3.download_cotahist_day(date(2026, 8, 14), attempts=1)
    except RuntimeError as exc:
        assert "B3 ZIP-nedlasting feilet" in str(exc)
    else:
        raise AssertionError("oversized daily COTAHIST should fail")

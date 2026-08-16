from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

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
    """An unrelated COTAHIST instrument may use another quotation factor.

    It must not make the BMOB3 import fail. This reproduces the issue discovered
    during the first live B3 2025 backfill.
    """
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

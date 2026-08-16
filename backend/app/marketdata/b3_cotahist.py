from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO, TextIOWrapper
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

B3_YEARLY_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"


@dataclass(frozen=True)
class B3DailyClose:
    trading_date: str
    ticker: str
    close: Decimal
    currency: str
    isin: str
    trades: int
    volume: Decimal
    quotation_factor: int


def _implied_two_decimals(raw: str) -> Decimal:
    raw = raw.strip()
    if not raw:
        return Decimal("0")
    return Decimal(raw) / Decimal("100")


def parse_cotahist_line(line: str) -> B3DailyClose | None:
    """Parse one official B3 COTAHIST register-01 line.

    The layout is fixed width (245 bytes). For equity NAV we only accept round-lot
    cash-market records and unit quotation factors. A non-unit factor is rejected
    rather than silently converting the price incorrectly.
    """
    line = line.rstrip("\r\n")
    if len(line) < 245 or line[0:2] != "01":
        return None

    bdi_code = line[10:12]
    market_type = line[24:27]
    if bdi_code != "02" or market_type != "010":
        return None

    quotation_factor = int(line[210:217] or "0")
    if quotation_factor != 1:
        raise ValueError(f"Uventet B3 quotation factor: {quotation_factor}")

    raw_date = line[2:10]
    date.fromisoformat(f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}")

    return B3DailyClose(
        trading_date=f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}",
        ticker=line[12:24].strip(),
        close=_implied_two_decimals(line[108:121]),
        currency=line[52:56].strip() or "R$",
        isin=line[230:242].strip(),
        trades=int(line[147:152] or "0"),
        volume=_implied_two_decimals(line[170:188]),
        quotation_factor=quotation_factor,
    )


def iter_ticker_from_text(lines, ticker: str):
    """Yield only records for one ticker without fully parsing the whole B3 universe.

    A yearly COTAHIST file contains equities, options and many other instruments.
    Checking the fixed-width ticker field first avoids Decimal/date parsing for millions
    of irrelevant rows and makes Raspberry Pi backfills substantially cheaper.
    """
    target = ticker.strip().upper()
    for line in lines:
        if len(line) < 24 or line[0:2] != "01":
            continue
        if line[12:24].strip().upper() != target:
            continue
        parsed = parse_cotahist_line(line)
        if parsed is not None:
            yield parsed


def parse_cotahist_zip_bytes(payload: bytes, ticker: str) -> list[B3DailyClose]:
    with ZipFile(BytesIO(payload)) as archive:
        members = [name for name in archive.namelist() if name.upper().endswith(".TXT")]
        if len(members) != 1:
            raise ValueError(f"Forventet én COTAHIST TXT-fil, fant {len(members)}")
        with archive.open(members[0]) as raw:
            with TextIOWrapper(raw, encoding="latin-1") as text:
                return list(iter_ticker_from_text(text, ticker))


def parse_cotahist_zip_file(path: str | Path, ticker: str) -> list[B3DailyClose]:
    return parse_cotahist_zip_bytes(Path(path).read_bytes(), ticker)


def download_cotahist_year(year: int, timeout: int = 30) -> bytes:
    if year < 1986 or year > date.today().year:
        raise ValueError(f"Ugyldig B3-år: {year}")
    url = B3_YEARLY_URL.format(year=year)
    request = Request(url, headers={"User-Agent": "otello-tracker/0.4 (+private research)"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception as exc:
        raise RuntimeError(
            "B3-nedlasting feilet. B3 kan kreve CAPTCHA; last i så fall ned "
            f"COTAHIST_A{year}.ZIP manuelt fra B3 og importer den lokale ZIP-filen."
        ) from exc

    if not payload.startswith(b"PK"):
        raise RuntimeError("B3 svarte ikke med en ZIP-fil")
    return payload

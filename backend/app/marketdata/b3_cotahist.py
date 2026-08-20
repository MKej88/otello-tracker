from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from http.client import IncompleteRead
from io import BytesIO, TextIOWrapper
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import ZipFile

B3_YEARLY_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"
B3_DAILY_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{date_ddmmyyyy}.ZIP"
MAX_DAILY_ZIP_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class B3DailyClose:
    trading_date: str
    ticker: str
    open: Decimal
    high: Decimal
    low: Decimal
    average: Decimal
    close: Decimal
    currency: str
    isin: str
    trades: int
    quantity: int
    volume: Decimal
    quotation_factor: int


def _implied_two_decimals(raw: str) -> Decimal:
    raw = raw.strip()
    if not raw:
        return Decimal("0")
    return Decimal(raw) / Decimal("100")


def parse_cotahist_line(line: str) -> B3DailyClose | None:
    """Parse one official B3 COTAHIST register-01 line.

    The fixed-width fields follow B3's public COTAHIST layout: opening, high, low,
    average and close prices are stored with two implied decimals; QUATOT is the total
    quantity of securities traded and VOLTOT is the financial trading value. For equity
    NAV we only accept round-lot cash-market records and unit quotation factors.
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
        open=_implied_two_decimals(line[56:69]),
        high=_implied_two_decimals(line[69:82]),
        low=_implied_two_decimals(line[82:95]),
        average=_implied_two_decimals(line[95:108]),
        close=_implied_two_decimals(line[108:121]),
        currency=line[52:56].strip() or "R$",
        isin=line[230:242].strip(),
        trades=int(line[147:152] or "0"),
        quantity=int(line[152:170] or "0"),
        volume=_implied_two_decimals(line[170:188]),
        quotation_factor=quotation_factor,
    )


def iter_ticker_from_text(lines, ticker: str):
    """Yield only records for one ticker without fully parsing the whole B3 universe."""
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


def _download_zip(
    url: str,
    *,
    timeout: int,
    attempts: int,
    max_bytes: int | None = None,
    missing_is_none: bool = False,
) -> bytes | None:
    if attempts < 1:
        raise ValueError("attempts må være minst 1")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = Request(
            url,
            headers={
                "User-Agent": "otello-tracker/0.4 (+private research)",
                "Connection": "close",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                content_length = response.headers.get("Content-Length")
                if max_bytes is not None and content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise RuntimeError("B3 ZIP exceeds configured size limit")
                    except ValueError:
                        pass
                payload = response.read((max_bytes + 1) if max_bytes is not None else -1)
            if max_bytes is not None and len(payload) > max_bytes:
                raise RuntimeError("B3 ZIP exceeds configured size limit")
            if not payload.startswith(b"PK"):
                raise RuntimeError("B3 svarte ikke med en ZIP-fil")
            return payload
        except HTTPError as exc:
            if missing_is_none and exc.code == 404:
                return None
            last_error = exc
        except (IncompleteRead, URLError, TimeoutError, OSError, RuntimeError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(min(2 ** (attempt - 1), 8))

    raise RuntimeError(f"B3 ZIP-nedlasting feilet etter {attempts} forsøk: {url}") from last_error


def download_cotahist_day(
    trading_day: date,
    timeout: int = 30,
    attempts: int = 3,
) -> bytes | None:
    """Download one small official B3 daily COTAHIST ZIP.

    B3 returns 404 until the file for a session has been published. That is a normal
    availability state rather than an error, so callers receive None and may fall back
    to the previous B3 trading day. Daily files are size-bounded because production only
    needs one compact completed-session file, not an unbounded response.
    """
    if trading_day.year < 1986 or trading_day > date.today():
        raise ValueError(f"Ugyldig B3-handelsdato: {trading_day.isoformat()}")
    url = B3_DAILY_URL.format(date_ddmmyyyy=trading_day.strftime("%d%m%Y"))
    return _download_zip(
        url,
        timeout=timeout,
        attempts=attempts,
        max_bytes=MAX_DAILY_ZIP_BYTES,
        missing_is_none=True,
    )


def download_cotahist_year(
    year: int,
    timeout: int = 60,
    attempts: int = 4,
) -> bytes:
    """Download one official B3 annual COTAHIST ZIP with bounded retries.

    The annual file is retained for bootstrap and historical backfill. Normal production
    refreshes use the much smaller daily COTAHIST file instead.
    """
    if year < 1986 or year > date.today().year:
        raise ValueError(f"Ugyldig B3-år: {year}")
    url = B3_YEARLY_URL.format(year=year)
    payload = _download_zip(url, timeout=timeout, attempts=attempts)
    if payload is None:
        raise RuntimeError(f"B3-nedlasting av COTAHIST_A{year}.ZIP returnerte ingen fil")
    return payload

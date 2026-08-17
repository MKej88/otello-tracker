from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext
from io import StringIO

getcontext().prec = 28

OTEC_2022_DISTRIBUTION_EX_DATE = "2022-08-09"
OTEC_2022_DISTRIBUTION_NOK = Decimal("21")
MAX_PLAUSIBLE_OTEC_NOK = Decimal("500")


@dataclass(frozen=True)
class InvestingDailyClose:
    trading_date: str
    close: Decimal
    source_close: Decimal
    quality: str
    adjustment_factor: Decimal | None


@dataclass(frozen=True)
class AdjustmentInfo:
    ex_date: str
    dividend_nok: Decimal
    last_including_date: str
    adjusted_close_last_including: Decimal
    reconstructed_close_last_including: Decimal
    backward_adjustment_factor: Decimal
    reconstruction_multiplier: Decimal


def _detect_dialect(text: str) -> csv.Dialect:
    sample = "\n".join(text.splitlines()[:10])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _parse_decimal(value: str) -> Decimal:
    """Parse either decimal-comma or decimal-point exports without silently scaling price."""
    cleaned = value.strip().replace("\u00a0", "").replace(" ", "")
    if not cleaned:
        raise ValueError("Tom Investing-pris")

    if "," in cleaned and "." in cleaned:
        # The right-most separator is decimal; the other separator is thousands.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # OTEC exports can be localized as 17,20. Treat a lone comma as decimal.
        cleaned = cleaned.replace(",", ".")

    result = Decimal(cleaned)
    if result <= 0 or result > MAX_PLAUSIBLE_OTEC_NOK:
        raise ValueError(f"Urealistisk OTEC-pris i Investing CSV: {value}")
    return result


def _parse_date(value: str) -> str:
    value = value.strip()
    for fmt in (
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Kunne ikke tolke Investing-dato: {value}")


def parse_investing_historical_csv(text: str) -> list[tuple[str, Decimal]]:
    """Parse a manually exported Investing.com historical-price CSV.

    Only Date and Price are required. The delimiter and decimal representation may be
    localized. The raw price may be dividend-adjusted by the vendor; reconstruction is
    deliberately handled separately so the transformation is visible and testable.
    """
    clean_text = text.lstrip("\ufeff")
    reader = csv.DictReader(StringIO(clean_text), dialect=_detect_dialect(clean_text))
    fields = set(reader.fieldnames or [])
    if not {"Date", "Price"}.issubset(fields):
        raise ValueError(f"Investing CSV må inneholde Date og Price. Fant: {reader.fieldnames}")

    result: list[tuple[str, Decimal]] = []
    seen: set[str] = set()
    for row in reader:
        raw_date = (row.get("Date") or "").strip()
        raw_price = (row.get("Price") or "").strip()
        if not raw_date or not raw_price:
            continue
        trading_date = _parse_date(raw_date)
        if trading_date in seen:
            raise ValueError(f"Duplikatdato i Investing CSV: {trading_date}")
        seen.add(trading_date)
        result.append((trading_date, _parse_decimal(raw_price)))

    if not result:
        raise ValueError("Investing CSV inneholder ingen prisrader")
    return sorted(result, key=lambda item: item[0])


def reconstruct_otec_2022_distribution(
    rows: list[tuple[str, Decimal]],
    *,
    ex_date: str = OTEC_2022_DISTRIBUTION_EX_DATE,
    dividend_nok: Decimal = OTEC_2022_DISTRIBUTION_NOK,
) -> tuple[list[InvestingDailyClose], AdjustmentInfo]:
    """Reverse Investing's backward dividend adjustment around Otello's NOK 21 payout.

    Otello's last day including the right was 2022-08-08 and ex-date was 2022-08-09.
    For a standard backward cash-dividend adjustment, the adjusted close on the last
    cum-dividend day equals raw_close - dividend. Hence raw_close = adjusted_close +
    dividend, which gives the adjustment factor used for every prior observation.

    Reconstructed values are rounded to øre because the exported adjusted source is
    itself rounded to two decimals. They are therefore marked RECONSTRUCTED rather
    than DIRECT.
    """
    ex = date.fromisoformat(ex_date)
    before = [(d, p) for d, p in rows if date.fromisoformat(d) < ex]
    if not before:
        raise ValueError("Investing-serien mangler dato før Otello-utdelingen")

    last_date, adjusted_last = max(before, key=lambda item: item[0])
    if adjusted_last <= 0:
        raise ValueError("Ugyldig justert sluttkurs før utbytte")

    raw_last = adjusted_last + dividend_nok
    factor = adjusted_last / raw_last
    multiplier = raw_last / adjusted_last

    result: list[InvestingDailyClose] = []
    for trading_date, source_close in rows:
        if date.fromisoformat(trading_date) < ex:
            reconstructed = (source_close * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if reconstructed <= 0 or reconstructed > MAX_PLAUSIBLE_OTEC_NOK:
                raise ValueError(
                    f"Urealistisk rekonstruert OTEC-pris {reconstructed} på {trading_date}"
                )
            result.append(
                InvestingDailyClose(
                    trading_date=trading_date,
                    close=reconstructed,
                    source_close=source_close,
                    quality="RECONSTRUCTED",
                    adjustment_factor=factor,
                )
            )
        else:
            result.append(
                InvestingDailyClose(
                    trading_date=trading_date,
                    close=source_close,
                    source_close=source_close,
                    quality="DIRECT",
                    adjustment_factor=None,
                )
            )

    return result, AdjustmentInfo(
        ex_date=ex_date,
        dividend_nok=dividend_nok,
        last_including_date=last_date,
        adjusted_close_last_including=adjusted_last,
        reconstructed_close_last_including=raw_last,
        backward_adjustment_factor=factor,
        reconstruction_multiplier=multiplier,
    )

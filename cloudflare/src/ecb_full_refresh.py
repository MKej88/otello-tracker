from __future__ import annotations

import csv
import hashlib
import io
import urllib.parse
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable

try:
    from .bounded_response import read_response_bytes
except ImportError:
    from bounded_response import read_response_bytes

ECB_EXR_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.BRL+NOK+USD.EUR.SP00.A"
MAX_ECB_BYTES = 2 * 1024 * 1024


def build_ecb_url(start_date: str, end_date: str) -> str:
    query = urllib.parse.urlencode(
        {
            "startPeriod": start_date,
            "endPeriod": end_date,
            "format": "csvdata",
            "detail": "dataonly",
        }
    )
    return f"{ECB_EXR_URL}?{query}"


def parse_ecb_cross_rates(text: str) -> list[tuple[str, str, Decimal]]:
    reader = csv.DictReader(io.StringIO(text))
    required = {"CURRENCY", "TIME_PERIOD", "OBS_VALUE"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError(f"Uventet ECB CSV-felter: {reader.fieldnames}")

    rows: dict[str, dict[str, Decimal]] = {}
    for row in reader:
        currency = str(row.get("CURRENCY") or "").strip().upper()
        if currency not in {"BRL", "NOK", "USD"}:
            continue
        value = str(row.get("OBS_VALUE") or "").strip()
        if not value:
            continue
        rows.setdefault(str(row["TIME_PERIOD"]), {})[currency] = Decimal(value)

    result: list[tuple[str, str, Decimal]] = []
    for trading_date, values in sorted(rows.items()):
        nok = values.get("NOK")
        if nok is None:
            continue
        for base in ("BRL", "USD"):
            denominator = values.get(base)
            if denominator is None or denominator == 0:
                continue
            result.append((trading_date, base, nok / denominator))
    return result


async def _download_ecb(
    url: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> bytes:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    response = await fetcher(
        url,
        headers={
            "Accept": "text/csv,*/*;q=0.8",
            "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
        },
    )
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(f"ECB EXR feilet med HTTP {getattr(response, 'status', 'unknown')}")
    return await read_response_bytes(response, max_bytes=MAX_ECB_BYTES, label="ECB EXR CSV")


async def refresh_ecb_fx(
    repository,
    *,
    target_date: str,
    lookback_days: int = 21,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    target = date.fromisoformat(target_date)
    start = (target - timedelta(days=max(7, lookback_days))).isoformat()
    url = build_ecb_url(start, target_date)
    payload = await _download_ecb(url, fetcher=fetcher)
    rows = parse_ecb_cross_rates(payload.decode("utf-8-sig"))
    if not rows:
        raise ValueError("ECB-returneringen inneholdt ingen BRL/NOK eller USD/NOK-rader")

    digest = hashlib.sha256(payload).hexdigest()
    document_id = await repository.create_source_document(
        source_code="ECB",
        external_id=f"exr-cross:{start}:{target_date}",
        document_type="API_RESPONSE",
        title="ECB daily reference rates used for BRL/NOK and USD/NOK",
        url=url,
        published_at=f"{target_date}T00:00:00Z",
        content_sha256=digest,
        metadata={
            "derived_pairs": ["BRL/NOK", "USD/NOK"],
            "method": "EUR cross",
            "from": start,
            "to": target_date,
            "workflow": "cloudflare_full_refresh",
        },
    )
    source_id = await repository.source_id("ECB")
    written = 0
    for trading_date, base, rate in rows:
        observed_at = f"{trading_date}T00:00:00Z"
        await repository.run(
            """
            INSERT INTO fx_rates(
                base_currency, quote_currency, observed_at, rate,
                source_id, source_document_id
            ) VALUES (?, 'NOK', ?, ?, ?, ?)
            ON CONFLICT(base_currency, quote_currency, observed_at, source_id)
            DO UPDATE SET rate=excluded.rate,
                source_document_id=excluded.source_document_id,
                fetched_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            (base, observed_at, format(rate, "f"), source_id, document_id),
        )
        written += 1

    return {
        "status": "ok",
        "from": start,
        "to": target_date,
        "rows_written": written,
        "source_document_id": document_id,
        "content_sha256": digest,
    }

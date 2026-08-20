from __future__ import annotations

import hashlib
import json
import urllib.parse
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable

try:
    from .bounded_response import read_response_bytes
    from .r2_archive import archive_bytes
except ImportError:
    from bounded_response import read_response_bytes
    from r2_archive import archive_bytes

NORGES_BANK_EXR_BASE = "https://data.norges-bank.no/api/data/EXR/B.BRL+USD.NOK.SP"
FX_BASE_CURRENCIES = ("BRL", "USD")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
FX_BACKTEST_HISTORY_START = "2023-12-20"


def build_norges_bank_url(start_date: str, end_date: str) -> str:
    query = urllib.parse.urlencode(
        {
            "startPeriod": start_date,
            "endPeriod": end_date,
            "format": "sdmx-json",
            "locale": "en",
        }
    )
    return f"{NORGES_BANK_EXR_BASE}?{query}"


def _payload_root(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("data")
    return nested if isinstance(nested, dict) and "dataSets" in nested else payload


def _dimension_values(dimension: dict[str, Any]) -> list[str]:
    values = dimension.get("values")
    if not isinstance(values, list):
        return []
    return [str(item.get("id") or "") for item in values if isinstance(item, dict)]


def _series_unit_multiplier(structure: dict[str, Any], series: dict[str, Any]) -> int:
    attributes = structure.get("attributes") or {}
    series_attributes = attributes.get("series") if isinstance(attributes, dict) else None
    raw_values = series.get("attributes")
    if not isinstance(series_attributes, list) or not isinstance(raw_values, list):
        return 0
    for index, attribute in enumerate(series_attributes):
        if not isinstance(attribute, dict) or str(attribute.get("id") or "").upper() != "UNIT_MULT":
            continue
        if index >= len(raw_values) or raw_values[index] is None:
            return 0
        try:
            value_index = int(raw_values[index])
            values = attribute.get("values") or []
            selected = values[value_index]
            raw = selected.get("id") if isinstance(selected, dict) else selected
            return int(str(raw))
        except (IndexError, TypeError, ValueError):
            raise ValueError("Norges Bank UNIT_MULT kunne ikke tolkes")
    return 0


def parse_norges_bank_sdmx_json(payload: bytes | str | dict[str, Any]) -> list[tuple[str, str, Decimal]]:
    if isinstance(payload, bytes):
        parsed = json.loads(payload.decode("utf-8-sig"))
    elif isinstance(payload, str):
        parsed = json.loads(payload)
    else:
        parsed = payload
    if not isinstance(parsed, dict):
        raise ValueError("Norges Bank-returneringen er ikke et JSON-objekt")

    root = _payload_root(parsed)
    data_sets = root.get("dataSets")
    structure = root.get("structure")
    if not isinstance(data_sets, list) or not data_sets or not isinstance(structure, dict):
        raise ValueError("Norges Bank SDMX-JSON mangler dataSets/structure")

    dimensions = structure.get("dimensions") or {}
    series_dimensions = dimensions.get("series") if isinstance(dimensions, dict) else None
    observation_dimensions = dimensions.get("observation") if isinstance(dimensions, dict) else None
    if not isinstance(series_dimensions, list) or not isinstance(observation_dimensions, list):
        raise ValueError("Norges Bank SDMX-JSON mangler dimensjoner")

    dimension_ids = [str(item.get("id") or "") for item in series_dimensions if isinstance(item, dict)]
    required = {"FREQ", "BASE_CUR", "QUOTE_CUR", "TENOR"}
    if not required.issubset(set(dimension_ids)):
        raise ValueError(f"Uventede Norges Bank-seriedimensjoner: {dimension_ids}")
    positions = {name: dimension_ids.index(name) for name in required}
    values_by_dimension = {
        str(item.get("id") or ""): _dimension_values(item)
        for item in series_dimensions
        if isinstance(item, dict)
    }

    time_dimension = next(
        (item for item in observation_dimensions if isinstance(item, dict) and item.get("id") == "TIME_PERIOD"),
        None,
    )
    if time_dimension is None:
        raise ValueError("Norges Bank SDMX-JSON mangler TIME_PERIOD")
    time_values = _dimension_values(time_dimension)

    series_map = data_sets[0].get("series") if isinstance(data_sets[0], dict) else None
    if not isinstance(series_map, dict):
        raise ValueError("Norges Bank SDMX-JSON mangler serier")

    rows: list[tuple[str, str, Decimal]] = []
    found_bases: set[str] = set()
    for series_key, series in series_map.items():
        if not isinstance(series, dict):
            continue
        try:
            indexes = [int(value) for value in str(series_key).split(":")]
            freq = values_by_dimension["FREQ"][indexes[positions["FREQ"]]]
            base = values_by_dimension["BASE_CUR"][indexes[positions["BASE_CUR"]]]
            quote = values_by_dimension["QUOTE_CUR"][indexes[positions["QUOTE_CUR"]]]
            tenor = values_by_dimension["TENOR"][indexes[positions["TENOR"]]]
        except (IndexError, KeyError, ValueError) as exc:
            raise ValueError(f"Ugyldig Norges Bank-serienøkkel: {series_key}") from exc
        if base not in FX_BASE_CURRENCIES:
            continue
        if freq != "B" or quote != "NOK" or tenor != "SP":
            raise ValueError(f"Uventet Norges Bank-serie: {freq}/{base}/{quote}/{tenor}")
        unit_multiplier = _series_unit_multiplier(structure, series)
        if unit_multiplier != 0:
            raise ValueError(f"Uventet UNIT_MULT={unit_multiplier} for {base}/NOK")

        observations = series.get("observations")
        if not isinstance(observations, dict):
            continue
        for observation_key, observation in observations.items():
            try:
                time_index = int(str(observation_key).split(":")[0])
                trading_date = time_values[time_index]
                raw_value = observation[0] if isinstance(observation, list) else observation
                rate = Decimal(str(raw_value))
            except (IndexError, InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("Ugyldig observasjon fra Norges Bank") from exc
            if rate <= 0:
                raise ValueError(f"Ugyldig {base}/NOK-kurs: {rate}")
            rows.append((trading_date, base, rate))
            found_bases.add(base)

    if not rows:
        raise ValueError("Norges Bank-returneringen inneholdt ingen BRL/NOK eller USD/NOK-rader")
    missing = sorted(set(FX_BASE_CURRENCIES) - found_bases)
    if missing:
        raise ValueError(f"Norges Bank-returneringen manglet valuta: {', '.join(missing)}")
    return sorted(rows)


async def _download_norges_bank(
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
            "Accept": "application/vnd.sdmx.data+json;version=1.0.0,application/json,*/*;q=0.8",
            "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
        },
    )
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(f"Norges Bank EXR feilet med HTTP {getattr(response, 'status', 'unknown')}")
    return await read_response_bytes(response, max_bytes=MAX_RESPONSE_BYTES, label="Norges Bank EXR JSON")


async def _norges_bank_coverage(repository) -> tuple[bool, dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT fr.base_currency, COUNT(*) AS n,
               MIN(substr(fr.observed_at,1,10)) AS min_date,
               MAX(substr(fr.observed_at,1,10)) AS max_date
        FROM fx_rates fr
        JOIN sources s ON s.id=fr.source_id
        WHERE fr.quote_currency='NOK'
          AND fr.base_currency IN ('BRL','USD')
          AND s.code='NORGES_BANK'
        GROUP BY fr.base_currency
        ORDER BY fr.base_currency
        """
    )
    coverage = {str(row["base_currency"]): row for row in rows}
    complete = all(
        currency in coverage
        and str(coverage[currency].get("min_date") or "9999-12-31") <= FX_BACKTEST_HISTORY_START
        and int(coverage[currency].get("n") or 0) >= 450
        for currency in FX_BASE_CURRENCIES
    )
    return complete, coverage


async def refresh_norges_bank_fx(
    repository,
    *,
    target_date: str,
    lookback_days: int = 21,
    archive_bucket: Any | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    target = date.fromisoformat(target_date)
    auto_backtest_history = False
    if lookback_days == 21:
        complete, _ = await _norges_bank_coverage(repository)
        if not complete:
            history_start = date.fromisoformat(FX_BACKTEST_HISTORY_START)
            lookback_days = max(lookback_days, (target - history_start).days)
            auto_backtest_history = True

    start = (target - timedelta(days=max(7, lookback_days))).isoformat()
    url = build_norges_bank_url(start, target_date)
    payload = await _download_norges_bank(url, fetcher=fetcher)
    rows = parse_norges_bank_sdmx_json(payload)

    digest = hashlib.sha256(payload).hexdigest()
    archived = (
        await archive_bytes(
            archive_bucket,
            payload,
            source="norges-bank",
            kind="exr",
            logical_date=target_date,
            filename=f"exr-{start}-{target_date}-{digest[:12]}.json",
        )
        if archive_bucket is not None
        else None
    )
    document_id = await repository.create_source_document(
        source_code="NORGES_BANK",
        external_id=f"exr-direct:{start}:{target_date}",
        document_type="API_RESPONSE",
        title="Norges Bank daily reference rates for BRL/NOK and USD/NOK",
        url=url,
        published_at=f"{target_date}T00:00:00Z",
        content_sha256=digest,
        metadata={
            "pairs": ["BRL/NOK", "USD/NOK"],
            "method": "direct NOK quote",
            "from": start,
            "to": target_date,
            "workflow": "cloudflare_full_refresh",
            "r2_key": archived.get("r2_key") if archived else None,
            "archive_policy": "CONTENT_ADDRESSED_R2" if archived else "NOT_REQUESTED",
            "auto_fx_backtest_history": auto_backtest_history,
        },
    )
    source_id = await repository.source_id("NORGES_BANK")
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
        "provider": "Norges Bank",
        "from": start,
        "to": target_date,
        "rows_written": written,
        "source_document_id": document_id,
        "content_sha256": digest,
        "r2_archive": archived,
        "auto_fx_backtest_history": auto_backtest_history,
    }


async def ensure_fx_backtest_history(
    repository,
    *,
    target_date: str,
    archive_bucket: Any | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    complete, coverage = await _norges_bank_coverage(repository)
    if complete:
        return {
            "status": "ok",
            "skipped": True,
            "reason": "norges_bank_fx_history_already_present",
            "coverage": coverage,
        }

    target = date.fromisoformat(target_date)
    start = date.fromisoformat(FX_BACKTEST_HISTORY_START)
    lookback_days = max(7, (target - start).days)
    result = await refresh_norges_bank_fx(
        repository,
        target_date=target_date,
        lookback_days=lookback_days,
        archive_bucket=archive_bucket,
        fetcher=fetcher,
    )
    result["history_backfill"] = True
    return result

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import Request, urlopen

NORGES_BANK_EXR_BASE = "https://data.norges-bank.no/api/data/EXR/B.BRL+USD.NOK.SP"
FX_BASE_CURRENCIES = ("BRL", "USD")


@dataclass(frozen=True)
class CrossRate:
    trading_date: str
    base_currency: str
    quote_currency: str
    rate: Decimal


def build_norges_bank_url(start_date: str, end_date: str | None = None) -> str:
    query = {
        "startPeriod": start_date,
        "format": "sdmx-json",
        "locale": "en",
    }
    if end_date:
        query["endPeriod"] = end_date
    return f"{NORGES_BANK_EXR_BASE}?{urlencode(query)}"


def _payload_root(payload: dict) -> dict:
    nested = payload.get("data")
    return nested if isinstance(nested, dict) and "dataSets" in nested else payload


def _dimension_values(dimension: dict) -> list[str]:
    values = dimension.get("values")
    if not isinstance(values, list):
        return []
    return [str(item.get("id") or "") for item in values if isinstance(item, dict)]


def _series_unit_multiplier(structure: dict, series: dict) -> int:
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
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("Norges Bank UNIT_MULT kunne ikke tolkes") from exc
    return 0


def parse_norges_bank_sdmx_json(payload: str | bytes | dict) -> list[CrossRate]:
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

    rows: list[CrossRate] = []
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
            if not rate.is_finite() or rate <= 0:
                raise ValueError(f"Ugyldig {base}/NOK-kurs: {rate}")
            rows.append(CrossRate(trading_date, base, "NOK", rate))
            found_bases.add(base)

    if not rows:
        raise ValueError("Norges Bank-returneringen inneholdt ingen BRL/NOK eller USD/NOK-rader")
    missing = sorted(set(FX_BASE_CURRENCIES) - found_bases)
    if missing:
        raise ValueError(f"Norges Bank-returneringen manglet valuta: {', '.join(missing)}")
    return sorted(rows, key=lambda item: (item.trading_date, item.base_currency))


def fetch_norges_bank_json(
    start_date: str,
    end_date: str | None = None,
    timeout: int = 30,
) -> tuple[str, str]:
    url = build_norges_bank_url(start_date, end_date)
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.sdmx.data+json;version=1.0.0,application/json",
            "User-Agent": "otello-tracker/1.0 (+private research)",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return url, response.read().decode("utf-8-sig")

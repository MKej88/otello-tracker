from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from brazil_dashboard import (  # noqa: E402
    UpstreamJsonError,
    _load_focus,
    normalize_focus_indicator,
    parse_focus_snapshot,
)
from brazil_investor_insights import build_focus_trend  # noqa: E402
from brazil_focus_resilience import resolve_annual_focus  # noqa: E402

LABELS = {
    "selic": "Selic",
    "ipca": "IPCA",
    "gdp": "PIB Total",
    "usd_brl": "Câmbio",
}


def rows(
    ref_date: str, first_year: int, *, missing: tuple[str, int] | None = None
) -> list[dict[str, Any]]:
    result = []
    for indicator, label in LABELS.items():
        for year in (first_year, first_year + 1):
            if missing == (indicator, year):
                continue
            result.append(
                {
                    "Indicador": label,
                    "DataReferencia": str(year),
                    "Data": ref_date,
                    "Mediana": {
                        "selic": 12.5,
                        "ipca": 4.4,
                        "gdp": 2.1,
                        "usd_brl": 5.2,
                    }[indicator]
                    + (year - first_year) / 10,
                    "Media": 1,
                    "Minimo": 1,
                    "Maximo": 1,
                    "numeroRespondentes": 100,
                }
            )
    return result


def test_latest_complete_snapshot_is_selected_without_mixing_dates() -> None:
    payload = {"value": rows("2026-09-04", 2026) + rows("2026-08-28", 2026)}
    snapshot = parse_focus_snapshot(payload, as_of_date="2026-09-11")

    assert snapshot["ref_date"] == "2026-09-04"
    assert {
        point["survey_date"]
        for indicator in snapshot["values"].values()
        for point in indicator.values()
    } == {"2026-09-04"}


def test_incomplete_latest_snapshot_falls_back_to_complete_date() -> None:
    payload = {
        "value": rows("2026-09-04", 2026, missing=("gdp", 2027))
        + rows("2026-08-28", 2026)
    }
    snapshot = parse_focus_snapshot(payload, as_of_date="2026-09-11")

    assert snapshot["ref_date"] == "2026-08-28"
    assert set(snapshot["values"]["gdp"]) == {"2026", "2027"}


def test_years_are_dynamic_across_new_year() -> None:
    december = parse_focus_snapshot(
        {"value": rows("2026-12-18", 2026)}, as_of_date="2026-12-20"
    )
    january = parse_focus_snapshot(
        {"value": rows("2026-12-30", 2027)}, as_of_date="2027-01-02"
    )

    assert (december["current_year"], december["next_year"]) == (2026, 2027)
    assert (january["current_year"], january["next_year"]) == (2027, 2028)


def test_indicator_names_are_normalized_in_one_mapping() -> None:
    assert normalize_focus_indicator("Selic") == "selic"
    assert normalize_focus_indicator("IPCA") == "ipca"
    assert normalize_focus_indicator("PIB Total") == "gdp"
    assert normalize_focus_indicator("PIB") == "gdp"
    assert normalize_focus_indicator("BNP") is None


def test_freshness_metadata_identifies_old_data() -> None:
    snapshot = parse_focus_snapshot(
        {"value": rows("2026-07-31", 2026)}, as_of_date="2026-09-11"
    )

    assert snapshot["latest_available_ref_date"] == "2026-07-31"
    assert snapshot["age_days"] == 42
    assert snapshot["stale"] is True


def test_trend_uses_current_ref_date_and_latest_snapshot_on_or_before_30d() -> None:
    current_snapshot = parse_focus_snapshot(
        {"value": rows("2026-09-04", 2026)}, as_of_date="2026-09-11"
    )
    current = {"values": current_snapshot["values"], "focus_meta": current_snapshot}
    available = rows("2026-08-07", 2026) + rows("2026-07-31", 2026)

    async def fake_load(
        as_of_date: str,
        *,
        current_year: int | None = None,
        require_complete: bool = False,
        fetcher: Any = None,
    ) -> dict[str, Any]:
        snapshot = parse_focus_snapshot(
            {"value": available}, as_of_date=as_of_date, current_year=current_year
        )
        return {"values": snapshot["values"], "focus_meta": snapshot}

    with patch("brazil_investor_insights.base._load_focus", fake_load):
        trend, status = asyncio.run(
            build_focus_trend(as_of_date="2026-09-11", current_focus=current)
        )

    assert status["comparison_dates"]["30d"] == "2026-08-05"
    assert trend["current_ref_date"] == "2026-09-04"
    assert trend["comparisons"]["30d"]["ref_date"] == "2026-07-31"
    assert trend["comparisons"]["30d"]["points_by_year"]["2027"]["gdp"]["change"] == 0


def test_exact_30d_snapshot_is_used_and_change_is_absolute_points() -> None:
    current_rows = rows("2026-09-04", 2026)
    previous_rows = rows("2026-08-05", 2026)
    for row in current_rows:
        if row["Indicador"] == "IPCA":
            row["Mediana"] = 4.65
    for row in previous_rows:
        if row["Indicador"] == "IPCA":
            row["Mediana"] = 4.80
    current_snapshot = parse_focus_snapshot(
        {"value": current_rows}, as_of_date="2026-09-11"
    )

    async def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        snapshot = parse_focus_snapshot(
            {"value": previous_rows}, as_of_date=args[0], current_year=2026
        )
        return {"values": snapshot["values"], "focus_meta": snapshot}

    with patch("brazil_investor_insights.base._load_focus", fake_load):
        trend, _ = asyncio.run(
            build_focus_trend(
                as_of_date="2026-09-11",
                current_focus={
                    "values": current_snapshot["values"],
                    "focus_meta": current_snapshot,
                },
            )
        )

    point = trend["comparisons"]["30d"]["points_by_year"]["2026"]["ipca"]
    assert trend["comparisons"]["30d"]["ref_date"] == "2026-08-05"
    assert round(point["change"], 2) == -0.15
    assert round(point["change_bp"]) == -15


def test_incomplete_historical_snapshot_falls_back_further() -> None:
    payload = {
        "value": rows("2026-08-05", 2026, missing=("selic", 2027))
        + rows("2026-07-29", 2026)
    }
    snapshot = parse_focus_snapshot(payload, as_of_date="2026-08-05")

    assert snapshot["ref_date"] == "2026-07-29"
    assert snapshot["values"]["selic"]["2027"]["median"] is not None


def test_focus_request_only_fetches_the_two_relevant_years() -> None:
    requested_urls: list[str] = []

    class Response:
        ok = True
        status = 200

        async def text(self) -> str:
            return json.dumps({"value": rows("2026-09-04", 2026)})

    async def fetcher(url: str, **kwargs: Any) -> Response:
        requested_urls.append(url)
        return Response()

    result = asyncio.run(_load_focus("2026-09-12", fetcher=fetcher))
    assert result["focus_meta"]["ref_date"] == "2026-09-04"
    assert len(requested_urls) == 4
    for requested_url in requested_urls:
        query = parse_qs(urlparse(requested_url).query)
        assert "DataReferencia eq '2026'" in query["$filter"][0]
        assert "DataReferencia eq '2027'" in query["$filter"][0]
        assert "baseCalculo eq 0" in query["$filter"][0]
        assert query["$top"] == ["150"]
        assert query["$select"] == [
            "Indicador,DataReferencia,Data,Mediana,Media,Minimo,Maximo,numeroRespondentes"
        ]


class ErrorResponse:
    def __init__(self, status: int, body: str) -> None:
        self.ok = False
        self.status = status
        self.body_text = body

    async def text(self) -> str:
        return self.body_text


def test_focus_http_403_is_diagnostic_and_not_retried() -> None:
    calls = 0

    async def fetcher(url: str, **kwargs: Any) -> ErrorResponse:
        nonlocal calls
        calls += 1
        return ErrorResponse(403, "request forbidden by upstream")

    try:
        asyncio.run(_load_focus("2026-09-12", fetcher=fetcher))
    except UpstreamJsonError as exc:
        assert exc.kind == "upstream_http_error"
        assert exc.http_status == 403
        assert "request forbidden" in str(exc)
    else:
        raise AssertionError("403 skulle ha feilet")
    assert calls == 4


def test_focus_retries_429_and_5xx_before_success() -> None:
    attempts: dict[str, int] = {}

    class Response:
        ok = True
        status = 200

        async def text(self) -> str:
            return json.dumps({"value": rows("2026-09-04", 2026)})

    async def fetcher(url: str, **kwargs: Any) -> Any:
        indicator = parse_qs(urlparse(url).query)["$filter"][0].split("'")[1]
        attempts[indicator] = attempts.get(indicator, 0) + 1
        if attempts[indicator] == 1:
            return ErrorResponse(429 if indicator == "IPCA" else 503, "temporary")
        return Response()

    result = asyncio.run(_load_focus("2026-09-12", fetcher=fetcher))

    assert result["ready"] is True
    assert set(attempts.values()) == {2}


def test_focus_invalid_json_is_distinguished_from_http_error() -> None:
    class Response:
        ok = True
        status = 200

        async def text(self) -> str:
            return "not-json"

    async def fetcher(url: str, **kwargs: Any) -> Response:
        return Response()

    try:
        asyncio.run(_load_focus("2026-09-12", fetcher=fetcher))
    except UpstreamJsonError as exc:
        assert exc.kind == "invalid_json"
        assert exc.http_status == 200
    else:
        raise AssertionError("Ugyldig JSON skulle ha feilet")


class FocusRepository:
    def __init__(self, cached: dict[str, Any] | None = None) -> None:
        self.cached = cached
        self.writes = 0

    async def first(self, query: str, params: tuple[Any, ...]) -> Any:
        if self.cached is None:
            return None
        return {"value": json.dumps(self.cached), "updated_at": "2026-09-01T00:00:00Z"}

    async def run_batch(self, statements: Any) -> None:
        self.writes += 1


def test_d1_last_good_precedes_bootstrap_and_live_replaces_both() -> None:
    cached_values = parse_focus_snapshot(
        {"value": rows("2026-09-04", 2026)}, as_of_date="2026-09-12"
    )["values"]
    repository = FocusRepository(
        {"values": cached_values, "source": "Banco Central do Brasil / Focus"}
    )

    cached, cached_status = asyncio.run(
        resolve_annual_focus(repository, None, as_of_date="2026-09-12")
    )
    assert cached["data_source"] == "LAST_GOOD_D1_CACHE"
    assert cached_status["fallback_source"] == "LAST_GOOD_D1_CACHE"

    live = {
        "ready": True,
        "values": parse_focus_snapshot(
            {"value": rows("2026-09-11", 2026)}, as_of_date="2026-09-12"
        )["values"],
    }
    resolved, live_status = asyncio.run(
        resolve_annual_focus(repository, live, as_of_date="2026-09-12")
    )
    assert resolved["data_source"] == "BCB_OLINDA_LIVE"
    assert resolved["fallback"] is False
    assert live_status["live_ready"] if "live_ready" in live_status else True
    assert repository.writes == 1


def test_bootstrap_is_only_used_without_live_or_d1() -> None:
    resolved, status = asyncio.run(
        resolve_annual_focus(FocusRepository(), None, as_of_date="2026-09-12")
    )

    assert resolved["data_source"] == "PUBLISHED_FOCUS_BOOTSTRAP"
    assert status["fallback_source"] == "PUBLISHED_FOCUS_BOOTSTRAP"

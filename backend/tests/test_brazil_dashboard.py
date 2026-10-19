from __future__ import annotations

import sys
from pathlib import Path

import pytest

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from brazil_dashboard import (  # noqa: E402
    _brl_nok,
    _default_as_of_date,
    _load_focus,
    _load_sgs_series,
    _series_payload,
    calendar_events,
    parse_focus_rows,
)


def test_default_as_of_date_uses_brazilian_calendar_day() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 9, 2, 1, 30, tzinfo=UTC)

    assert _default_as_of_date(now).isoformat() == "2026-09-01"


class _FxRepository:
    async def first(self, sql: str, params: tuple[str, ...]) -> dict[str, object]:
        if "ORDER BY substr(fr.observed_at,1,10) ASC" in sql:
            assert params == ("2026-07-31", "2026-07-24")
            return {"rate_date": "2026-08-01", "rate": "1.9000"}
        return {
            "rate_date": "2026-08-28",
            "rate": "1.8061",
            "source_code": "NORGES_BANK",
        }

    async def all(self, sql: str, params: tuple[str, ...]) -> list[dict[str, object]]:
        assert "ROW_NUMBER() OVER" in sql
        assert "AND substr(fr.observed_at,1,10)>=?" in sql
        assert params == ("2026-08-28", "2026-07-24")
        return [
            {"rate_date": "2026-08-28", "rate": "1.8061"},
            {"rate_date": "2026-08-27", "rate": "1.8200"},
        ]


def test_brl_nok_includes_chronological_history_for_sparkline() -> None:
    import asyncio

    result = asyncio.run(_brl_nok(_FxRepository(), "2026-09-29"))

    assert result["series"] == [
        {"date": "2026-08-27", "value": 1.82},
        {"date": "2026-08-28", "value": 1.8061},
    ]


class _Response:
    ok = True
    status = 200

    def __init__(self, payload: object) -> None:
        import json

        self._body = json.dumps(payload).encode()

    async def text(self) -> str:
        return self._body.decode()


def test_sgs_request_and_rows_are_capped_at_as_of_date() -> None:
    import asyncio
    from urllib.parse import parse_qs, urlparse

    seen: list[str] = []

    async def fetcher(url: str, **_kwargs: object) -> _Response:
        seen.append(url)
        return _Response([
            {"data": "28/08/2026", "valor": "14.5"},
            {"data": "30/08/2026", "valor": "99.0"},
        ])

    result = asyncio.run(_load_sgs_series("selic", as_of_date="2026-08-29", fetcher=fetcher))

    query = parse_qs(urlparse(seen[0]).query)
    assert query["dataFinal"] == ["29/08/2026"]
    assert result["date"] == "2026-08-28"
    assert result["value"] == 14.5


def test_sgs_rows_are_sorted_when_provider_changes_response_order() -> None:
    import asyncio

    async def fetcher(_url: str, **_kwargs: object) -> _Response:
        return _Response([
            {"data": "28/08/2026", "valor": "14.5"},
            {"data": "27/08/2026", "valor": "14.0"},
        ])

    result = asyncio.run(
        _load_sgs_series("selic", as_of_date="2026-08-29", fetcher=fetcher)
    )

    assert result["date"] == "2026-08-28"
    assert result["value"] == 14.5


@pytest.mark.parametrize(
    ("invalid_row", "expected_error"),
    [
        ({"data": "28/08/2026", "valor": "ikke-et-tall"}, "gyldig verdi"),
        ({"data": "", "valor": "14.5"}, "gyldig dato"),
        ("ufullstendig rad", "ikke et JSON-objekt"),
    ],
)
def test_sgs_rejects_partial_response_instead_of_showing_stale_value(
    invalid_row: object, expected_error: str
) -> None:
    import asyncio

    async def fetcher(_url: str, **_kwargs: object) -> _Response:
        return _Response(
            [{"data": "27/08/2026", "valor": "14.0"}, invalid_row]
        )

    with pytest.raises(ValueError, match=expected_error):
        asyncio.run(
            _load_sgs_series("selic", as_of_date="2026-08-29", fetcher=fetcher)
        )


def test_focus_request_and_parser_are_capped_at_as_of_date() -> None:
    import asyncio
    from urllib.parse import parse_qs, unquote, urlparse

    seen: list[str] = []

    async def fetcher(url: str, **_kwargs: object) -> _Response:
        seen.append(url)
        return _Response({"value": [
            {"Indicador": "Selic", "Data": "2026-08-28", "DataReferencia": "2026", "Mediana": 12.5},
            {"Indicador": "Selic", "Data": "2026-08-30", "DataReferencia": "2026", "Mediana": 9.0},
        ]})

    result = asyncio.run(_load_focus("2026-08-29", fetcher=fetcher))

    query = parse_qs(urlparse(seen[0]).query)
    assert "Data le '2026-08-29'" in unquote(query["$filter"][0])
    assert result["values"]["selic"]["2026"]["median"] == 12.5


def test_parse_focus_rows_keeps_current_and_next_year() -> None:
    payload = {
        "value": [
            {
                "Indicador": "Selic",
                "Data": "2026-08-28",
                "DataReferencia": "2026",
                "Media": 12.6,
                "Mediana": 12.5,
                "Minimo": 11.0,
                "Maximo": 14.0,
                "numeroRespondentes": 90,
            },
            {
                "Indicador": "IPCA",
                "Data": "2026-08-28",
                "DataReferencia": "2027",
                "Media": 3.9,
                "Mediana": 3.8,
                "Minimo": 3.2,
                "Maximo": 4.5,
                "numeroRespondentes": 100,
            },
            {
                "Indicador": "Câmbio",
                "Data": "2026-08-28",
                "DataReferencia": "2027",
                "Media": 5.2,
                "Mediana": 5.1,
                "Minimo": 4.7,
                "Maximo": 5.8,
                "numeroRespondentes": 80,
            },
            {
                "Indicador": "Selic",
                "Data": "2026-08-28",
                "DataReferencia": "2028",
                "Mediana": 9.0,
            },
        ]
    }

    result = parse_focus_rows(payload, as_of_date="2026-08-29")

    assert result["selic"]["2026"]["median"] == 12.5
    assert result["ipca"]["2027"]["median"] == 3.8
    assert result["usd_brl"]["2027"]["median"] == 5.1
    assert "2028" not in result["selic"]


def test_calendar_uses_focus_as_directional_proxy_not_event_consensus() -> None:
    focus = {
        "selic": {"2026": {"median": 12.5, "survey_date": "2026-08-28"}},
        "ipca": {"2026": {"median": 4.1, "survey_date": "2026-08-28"}},
        "gdp": {"2026": {"median": 2.1, "survey_date": "2026-08-28"}},
    }

    events = calendar_events(as_of_date="2026-08-29", focus=focus)
    copom = next(item for item in events if item["date"] == "2026-09-16" and item["kind"] == "copom")
    ipca = next(item for item in events if item["date"] == "2026-09-11" and item["name"] == "IPCA")
    gdp = next(item for item in events if item["date"] == "2026-09-01" and item["kind"] == "gdp")

    assert copom["expectation"]["value"] == 12.5
    assert copom["expectation"]["event_consensus"] is False
    assert "årsslutt" in copom["expectation"]["label"]
    assert ipca["expectation"]["value"] == 4.1
    assert gdp["expectation"]["value"] == 2.1
    assert copom["importance"] == "Høy"
    assert "Bemobi" in copom["bemobi_impact"] or "multippel" in copom["bemobi_impact"]


def test_calendar_has_labelled_rolling_preview_after_seed_ends() -> None:
    events = calendar_events(as_of_date="2027-02-19", focus={})

    assert events
    assert all(item["date"] >= "2027-02-19" for item in events)
    estimated = [item for item in events if item.get("date_status") == "estimated"]
    assert estimated
    assert all(item["source_url"].startswith("https://") for item in estimated)


def test_index_series_is_presented_as_monthly_change() -> None:
    rows = [
        {"date": "2026-06-01", "value": 100},
        {"date": "2026-07-01", "value": 101},
    ]

    result = _series_payload("ibc_br", rows)

    assert result["value"] == 1.0
    assert result["unit"] == "% m/m"
    assert result["series"][-1]["value"] == 101.0


class _DiagnosticResponse:
    def __init__(
        self, body: bytes, *, status: int, content_type: str | None
    ) -> None:
        self.body_bytes = body
        self.status = status
        self.ok = 200 <= status < 300
        self.headers = {"content-type": content_type} if content_type else {}

    async def text(self) -> str:
        return self.body_bytes.decode("utf-8")


@pytest.mark.parametrize(
    ("body", "status", "mime", "kind", "error_kind"),
    [
        (b"<html><body>PRIVATE_HTML_TOKEN</body></html>", 200,
         "text/html; charset=utf-8", "html", "invalid_json"),
        (b"", 200, "application/json", "empty", "invalid_json"),
        (b"<html><body>PRIVATE_DENIAL_TOKEN</body></html>", 403,
         "text/html", "html", "upstream_http_error"),
        (b"PRIVATE_PLAINTEXT_TOKEN", 200, "text/plain", "other", "invalid_json"),
        (b"{PRIVATE_INVALID_JSON_TOKEN", 200, "application/json",
         "json", "invalid_json"),
        (b"<HTML>PRIVATE_MISLABELLED_TOKEN</HTML>", 200,
         "application/json", "html", "invalid_json"),
    ],
)
def test_upstream_http_failures_record_only_safe_metadata(
    body: bytes, status: int, mime: str, kind: str, error_kind: str
) -> None:
    import asyncio
    import json

    from brazil_dashboard import UpstreamJsonError, _fetch_json, upstream_error_metadata

    async def fetcher(_url: str, **_kwargs: object) -> _DiagnosticResponse:
        return _DiagnosticResponse(body, status=status, content_type=mime)

    with pytest.raises(UpstreamJsonError) as caught:
        asyncio.run(_fetch_json("https://api.bcb.gov.br/test", fetcher=fetcher))
    error = caught.value
    meta = upstream_error_metadata(error)
    assert meta == {
        "error_kind": error_kind,
        "http_status": status,
        "content_type": mime.split(";", 1)[0],
        "response_bytes": len(body),
        "response_kind": kind,
    }
    # No body excerpts in exception messages or serialized source statuses.
    serialized = json.dumps({"error": str(error), **meta})
    assert "PRIVATE_" not in serialized
    assert "response_excerpt" not in serialized


def test_sgs_source_status_keeps_http_diagnostics_without_body() -> None:
    import asyncio
    import json
    from unittest.mock import AsyncMock, patch

    from brazil_dashboard import UpstreamJsonError, brazil_dashboard

    error = UpstreamJsonError(
        "Upstream returnerte ugyldig JSON: JSONDecodeError",
        kind="invalid_json", http_status=200, content_type="text/html",
        response_bytes=57, response_kind="html",
    )
    with patch("brazil_dashboard._load_sgs_series", new_callable=AsyncMock,
               side_effect=error), patch(
                   "brazil_dashboard._load_focus", new_callable=AsyncMock,
                   return_value={"values": {}}
               ), patch(
                   "brazil_dashboard._brl_nok", new_callable=AsyncMock,
                   return_value={"ready": False}
               ):
        dashboard = asyncio.run(brazil_dashboard(object(), as_of_date="2026-10-19"))
    for key in ("selic", "ipca_12m", "ibc_br", "ibc_services"):
        source = dashboard["source_status"][key]
        assert source["ready"] is False
        assert source["error_kind"] == "invalid_json"
        assert source["http_status"] == 200
        assert source["content_type"] == "text/html"
        assert source["response_bytes"] == 57
        assert source["response_kind"] == "html"
        assert "response_excerpt" not in source
    assert "response_excerpt" not in json.dumps(dashboard["source_status"])

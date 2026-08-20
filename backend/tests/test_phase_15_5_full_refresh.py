from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import newsweb_reconciliation as nw_reconcile  # noqa: E402
from b3_full_refresh import parse_bmob3_daily_zip  # noqa: E402
from cvm_full_refresh import classify_cvm_record, parse_cvm_ipe_archive  # noqa: E402
from d1_preflight import run_d1_preflight  # noqa: E402
from norges_bank_full_refresh import (  # noqa: E402
    norges_bank_history_start,
    parse_norges_bank_sdmx_json,
)
from otec_workflow_recovery import recover_otec_to_r2  # noqa: E402

from app.db.migration_runner import init_database  # noqa: E402
from app.history import seed_curated_history  # noqa: E402


def test_norges_bank_history_policy_is_rolling_ten_years() -> None:
    assert norges_bank_history_start("2026-08-20") == "2016-08-20"
    assert norges_bank_history_start("2024-02-29") == "2014-02-28"


def test_norges_bank_direct_rates_match_reference_values() -> None:
    payload = {
        "data": {
            "dataSets": [
                {
                    "series": {
                        "0:0:0:0": {
                            "attributes": [0, 0, 0, 0],
                            "observations": {"0": [Decimal("1.82")]},
                        },
                        "0:1:0:0": {
                            "attributes": [0, 0, 0, 0],
                            "observations": {"0": [Decimal("10.00")]},
                        },
                    }
                }
            ],
            "structure": {
                "dimensions": {
                    "series": [
                        {"id": "FREQ", "values": [{"id": "B"}]},
                        {"id": "BASE_CUR", "values": [{"id": "BRL"}, {"id": "USD"}]},
                        {"id": "QUOTE_CUR", "values": [{"id": "NOK"}]},
                        {"id": "TENOR", "values": [{"id": "SP"}]},
                    ],
                    "observation": [
                        {"id": "TIME_PERIOD", "values": [{"id": "2026-08-17"}]}
                    ],
                },
                "attributes": {
                    "series": [
                        {"id": "DECIMALS", "values": [{"id": "4"}]},
                        {"id": "CALCULATED", "values": [{"id": "0"}]},
                        {"id": "UNIT_MULT", "values": [{"id": "0"}]},
                        {"id": "COLLECTION", "values": [{"id": "A"}]},
                    ]
                },
            },
        }
    }
    rows = parse_norges_bank_sdmx_json(payload)
    assert rows == [
        ("2026-08-17", "BRL", Decimal("1.82")),
        ("2026-08-17", "USD", Decimal("10.00")),
    ]


def _b3_line(*, trading_date: str = "20260817", close: str = "0000000002281") -> str:
    chars = [" "] * 245

    def put(start: int, end: int, value: str) -> None:
        chars[start:end] = list(value.ljust(end - start)[: end - start])

    put(0, 2, "01")
    put(2, 10, trading_date)
    put(10, 12, "02")
    put(12, 24, "BMOB3")
    put(24, 27, "010")
    put(52, 56, "R$")
    put(108, 121, close)
    put(147, 152, "00123")
    put(170, 188, "000000000012345678")
    put(210, 217, "0000001")
    put(230, 242, "BRBMOBACNOR9")
    return "".join(chars)


def _zip_text(filename: str, text: str, *, encoding: str = "latin-1") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, text.encode(encoding))
    return buffer.getvalue()


def test_b3_daily_parser_extracts_official_bmob3_close() -> None:
    payload = _zip_text("COTAHIST_D17082026.TXT", _b3_line() + "\n")
    rows = parse_bmob3_daily_zip(payload)
    assert len(rows) == 1
    assert rows[0].trading_date == "2026-08-17"
    assert rows[0].close == Decimal("22.81")
    assert rows[0].trades == 123
    assert rows[0].isin == "BRBMOBACNOR9"


def _cvm_payload() -> bytes:
    headers = [
        "CNPJ_Companhia",
        "Nome_Companhia",
        "Codigo_CVM",
        "Data_Referencia",
        "Categoria",
        "Tipo",
        "Especie",
        "Assunto",
        "Data_Entrega",
        "Tipo_Apresentacao",
        "Protocolo_Entrega",
        "Versao",
        "Link_Download",
    ]
    row = [
        "09.042.817/0001-05",
        "BEMOBI MOBILE TECH S.A.",
        "25500",
        "2026-08-17",
        "Dados Econômico-Financeiros",
        "Press-release",
        "",
        "Apresentação de Resultados 2T26",
        "2026-08-17T18:00:00",
        "Apresentação",
        "123456",
        "1",
        "https://example.test/download?numProtocolo=123456&numSequencia=1",
    ]
    text = ";".join(headers) + "\n" + ";".join(row) + "\n"
    return _zip_text("ipe_cia_aberta_2026.csv", text, encoding="utf-8")


def test_cvm_parser_filters_bemobi_and_classifies_results_without_nav_effect() -> None:
    rows = parse_cvm_ipe_archive(_cvm_payload(), year=2026)
    assert len(rows) == 1
    record = rows[0]
    category, review, reason = classify_cvm_record(record)
    assert record.cvm_code == "25500"
    assert category == "RESULTS"
    assert review is False
    assert "result" in reason.lower()


def test_newsweb_reconciliation_forces_full_overlap_revalidation(monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []

    async def fake_history(repository, *, from_date, to_date, fetcher=None):
        calls.append(("history", from_date, to_date))
        return {"status": "ok", "archived": 2, "errors": []}

    async def fake_buybacks(repository, *, from_date, to_date, fetcher=None):
        calls.append(("buybacks", from_date, to_date))
        return {
            "status": "ok",
            "ingested": 1,
            "errors": [],
            "results": [{"large": "already durable in D1"}],
        }

    monkeypatch.setattr(nw_reconcile, "collect_newsweb_history", fake_history)
    monkeypatch.setattr(nw_reconcile, "collect_newsweb_buybacks", fake_buybacks)
    result = asyncio.run(nw_reconcile.reconcile_newsweb(object(), target_date="2026-08-17"))

    assert result["status"] == "ok"
    assert result["from"] == "2026-07-03"
    assert calls == [
        ("history", "2026-07-03", "2026-08-17"),
        ("buybacks", "2026-07-03", "2026-08-17"),
    ]
    assert "results" not in result["buybacks"]
    assert result["reconciliation_policy"] == "FULL_OVERLAP_BODY_HASH_REVALIDATION"


_EURONEXT_HEADER = (
    "TradingDateTime,PublicationDateTime,MifidInstrumentID,MifidPrice,"
    "MifidQuantity,MifidPriceNotation,MifidCurrency,Venue,"
    "TradeUniqueIdentifier,MissingPrice,VenueOfPublication\n"
)


def _euronext_zip() -> bytes:
    text = (
        "Euronext delayed-data notice\n"
        + _EURONEXT_HEADER
        + "2026-08-17T14:20:00Z,2026-08-17T14:35:00Z,NO0010040611,17.45,200,"
        "MONE,NOK,XOSL,workflow-trade,,XOSL\n"
    )
    return _zip_text("delayed.csv", text, encoding="utf-8")


class _Response:
    def __init__(self, payload: bytes, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.ok = status == 200
        self.headers = {"content-length": str(len(payload))}

    async def arrayBuffer(self):
        return self.payload


class _R2Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, payload: bytes):
        self.objects[key] = payload
        return {"key": key}


class _OTECRepository:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.prices: list[dict] = []

    async def create_source_document(self, **kwargs):
        self.documents.append(kwargs)
        return 41

    async def upsert_market_price(self, **kwargs):
        self.prices.append(kwargs)
        return 42


def test_otec_workflow_recovery_archives_raw_zip_and_preserves_last_semantics() -> None:
    payload = _euronext_zip()
    bucket = _R2Bucket()
    repository = _OTECRepository()

    async def fetcher(url, **kwargs):
        return _Response(payload)

    result = asyncio.run(
        recover_otec_to_r2(
            repository,
            bucket,
            target_date="2026-08-17",
            fetcher=fetcher,
        )
    )
    assert result["status"] == "ok"
    assert result["price_nok"] == "17.45"
    assert result["r2_key"] in bucket.objects
    assert repository.prices[0]["price_type"] == "LAST"
    assert repository.prices[0]["quality"] == "DIRECT"
    assert repository.documents[0]["metadata"]["feed_mode"] == "WORKFLOW_R2_RECOVERY"


class _SQLiteAsyncRepository:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    async def all(self, sql: str, parameters=()):
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        finally:
            connection.close()

    async def first(self, sql: str, parameters=()):
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None


def test_d1_preflight_uses_portable_queries_and_reports_blockers(tmp_path: Path) -> None:
    database = str(tmp_path / "preflight.db")
    init_database(database)
    seed_curated_history(database)
    result = asyncio.run(
        run_d1_preflight(
            _SQLiteAsyncRepository(database),
            target_date="2026-08-17",
            check_derived=False,
        )
    )
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["d1_query"]["status"] == "PASS"
    assert "curated_reference_data" in checks
    assert result["status"] in {"READY", "NOT_READY"}
    assert isinstance(result["blockers"], list)


def test_wrangler_config_keeps_fast_cron_and_adds_durable_full_refresh() -> None:
    config = json.loads((ROOT / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8"))
    assert config["triggers"]["crons"] == ["*/30 * * * *"]
    assert "python_workers" in config["compatibility_flags"]
    assert "python_workflows" in config["compatibility_flags"]
    workflow = config["workflows"][0]
    assert workflow["class_name"] == "FullRefreshWorkflow"
    assert workflow["schedules"] == ["35 3 * * *"]
    assert config["r2_buckets"][0]["binding"] == "SOURCE_ARCHIVE"

    entry = (ROOT / "cloudflare" / "src" / "entry.py").read_text(encoding="utf-8")
    assert "class FullRefreshWorkflow(WorkflowEntrypoint)" in entry
    assert "scheduled_day - timedelta(days=1)" in entry
    assert '"refresh Norges Bank FX"' in entry
    assert '"rebuild historical NAV with Norges Bank FX"' in entry
    assert '"D1 data health preflight"' in entry


def test_cloudflare_nav_fx_lookup_prefers_norges_bank_same_day() -> None:
    nav_source = (ROOT / "cloudflare" / "src" / "nav_refresh.py").read_text(encoding="utf-8")
    backtest_source = (ROOT / "cloudflare" / "src" / "fx_backtest.py").read_text(encoding="utf-8")
    for source in (nav_source, backtest_source):
        assert "WHEN 'NORGES_BANK' THEN 0" in source
        assert "WHEN 'ECB' THEN 1" in source

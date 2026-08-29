from __future__ import annotations

import csv
import io
import json
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable

try:
    from .bounded_response import read_response_bytes
except ImportError:
    from bounded_response import read_response_bytes

BEMOBI_CVM_CODE = "25500"
PARENT_NET_INCOME_ACCOUNT = "3.11.01"
CVM_ITR_URL = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/"
    "itr_cia_aberta_{year}.zip"
)
CVM_DFP_URL = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/"
    "dfp_cia_aberta_{year}.zip"
)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
NORMAL_REFRESH_DAYS = 7
MISSING_QUARTER_RETRY_DAYS = 2
_LAST_ATTEMPT_KEY = "bemobi_cvm_financials_last_attempt"
_LAST_SUCCESS_KEY = "bemobi_cvm_financials_last_success"
_COMMON_REQUIRED_COLUMNS = {
    "CD_CVM",
    "VERSAO",
    "MOEDA",
    "ESCALA_MOEDA",
    "ORDEM_EXERC",
    "DT_FIM_EXERC",
    "CD_CONTA",
    "VL_CONTA",
}
_FLOW_REQUIRED_COLUMNS = _COMMON_REQUIRED_COLUMNS | {"DT_INI_EXERC"}

# Standardized consolidated CVM statement lines. Adjusted Bemobi KPIs remain sourced
# from the official result release (also discovered through CVM), while these values are
# read directly from the structured ITR/DFP archives.
DRE_METRICS: dict[str, dict[str, str]] = {
    "reported_revenue_mbrl": {
        "account": "3.01",
        "label": "Receita de Venda de Bens e/ou Serviços",
    },
    "reported_ebit_mbrl": {
        "account": "3.05",
        "label": "Resultado Antes do Resultado Financeiro e dos Tributos",
    },
    "reported_net_income_parent_mbrl": {
        "account": PARENT_NET_INCOME_ACCOUNT,
        "label": "Atribuído a Sócios da Empresa Controladora",
    },
}
DFC_METRICS: dict[str, dict[str, str]] = {
    "reported_operating_cash_flow_mbrl": {
        "account": "6.01",
        "label": "Caixa Líquido Atividades Operacionais",
    },
}
BPA_METRICS: dict[str, dict[str, str]] = {
    "reported_cash_mbrl": {
        "account": "1.01.01",
        "label": "Caixa e Equivalentes de Caixa",
    },
}
BPP_METRICS: dict[str, dict[str, str]] = {
    "reported_borrowings_current_mbrl": {
        "account": "2.01.04",
        "label": "Empréstimos e Financiamentos - Circulante",
    },
    "reported_borrowings_noncurrent_mbrl": {
        "account": "2.02.01",
        "label": "Empréstimos e Financiamentos - Não Circulante",
    },
}
_REQUIRED_QUARTER_FIELDS = tuple(
    [*DRE_METRICS, *DFC_METRICS, *BPA_METRICS, *BPP_METRICS]
)


@dataclass(frozen=True)
class CVMIncomeObservation:
    year: int
    document_type: str
    period_start: str
    period_end: str
    reference_date: str | None
    version: int
    value_mbrl: float
    account_code: str = PARENT_NET_INCOME_ACCOUNT
    account_label: str | None = None
    statement: str = "DRE"


def _norm(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).strip().lower()


def _clean_cvm_code(value: str | None) -> str:
    text = str(value or "").strip()
    try:
        return str(int(text))
    except ValueError:
        return text.lstrip("0") or "0"


def _date_text(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    if len(text) == 10 and text[2] == "/" and text[5] == "/":
        day, month, year = text.split("/")
        return f"{year}-{month}-{day}"
    return text


def _decimal(value: str | None) -> Decimal:
    text = str(value or "").strip().replace(" ", "")
    if not text:
        raise ValueError("CVM VL_CONTA er tom")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Ugyldig CVM VL_CONTA: {value}") from exc


def _to_mbrl(value: str | None, scale: str | None) -> float:
    amount = _decimal(value)
    normalized_scale = _norm(scale)
    if normalized_scale in {"unidade", "unidades"}:
        amount /= Decimal("1000000")
    elif normalized_scale in {"mil", "milhar", "milhares"}:
        amount /= Decimal("1000")
    elif normalized_scale in {"milhao", "milhoes"}:
        pass
    elif normalized_scale in {"bilhao", "bilhoes"}:
        amount *= Decimal("1000")
    else:
        raise ValueError(f"Escala CVM ikke støttet: {scale}")
    return float(amount)


def _csv_encoding(sample: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("Kunne ikke dekode CVM CSV")


def _statement_member(
    archive: zipfile.ZipFile,
    *,
    document_type: str,
    year: int,
    statement: str,
) -> str:
    doc = document_type.lower()
    statement_upper = statement.upper()
    if statement_upper == "DFC":
        candidates = {
            f"{doc}_cia_aberta_dfc_mi_con_{year}.csv",
            f"{doc}_cia_aberta_dfc_md_con_{year}.csv",
        }
        matches = [
            name
            for name in archive.namelist()
            if name.rsplit("/", 1)[-1].lower() in candidates
        ]
        if len(matches) != 1:
            raise ValueError(
                f"CVM {document_type.upper()} {year} forventet én konsolidert DFC, fant {len(matches)}"
            )
        return matches[0]

    expected = f"{doc}_cia_aberta_{statement.lower()}_con_{year}.csv"
    matches = [
        name
        for name in archive.namelist()
        if name.rsplit("/", 1)[-1].lower() == expected
    ]
    if len(matches) != 1:
        raise ValueError(
            f"CVM {document_type.upper()} {year} forventet {expected}, fant {len(matches)}"
        )
    return matches[0]


def parse_statement_accounts_archive(
    payload: bytes,
    *,
    year: int,
    document_type: str,
    statement: str,
    account_codes: set[str],
) -> list[CVMIncomeObservation]:
    """Read selected standardized consolidated statement accounts for Bemobi."""
    doc = document_type.lower()
    statement_upper = statement.upper()
    if doc not in {"itr", "dfp"}:
        raise ValueError(f"Ukjent CVM dokumenttype: {document_type}")
    if statement_upper not in {"DRE", "DFC", "BPA", "BPP"}:
        raise ValueError(f"Ukjent CVM oppstilling: {statement}")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"CVM {doc.upper()} {year} er ikke en gyldig ZIP") from exc

    flow_statement = statement_upper in {"DRE", "DFC"}
    required = _FLOW_REQUIRED_COLUMNS if flow_statement else _COMMON_REQUIRED_COLUMNS
    observations: list[CVMIncomeObservation] = []
    with archive:
        member = _statement_member(
            archive,
            document_type=doc,
            year=year,
            statement=statement_upper,
        )
        with archive.open(member, "r") as raw_member:
            buffered = io.BufferedReader(raw_member, buffer_size=64 * 1024)
            encoding = _csv_encoding(bytes(buffered.peek(8192)[:8192]))
            with io.TextIOWrapper(buffered, encoding=encoding, newline="") as text_stream:
                reader = csv.DictReader(text_stream, delimiter=";")
                missing = sorted(required - set(reader.fieldnames or []))
                if missing:
                    raise ValueError(
                        f"CVM {doc.upper()} {statement_upper} {year} mangler kolonner: "
                        f"{', '.join(missing)}"
                    )
                for row in reader:
                    if _clean_cvm_code(row.get("CD_CVM")) != BEMOBI_CVM_CODE:
                        continue
                    account_code = str(row.get("CD_CONTA") or "").strip()
                    if account_code not in account_codes:
                        continue
                    if _norm(row.get("ORDEM_EXERC")) != "ultimo":
                        continue
                    if _norm(row.get("MOEDA")) not in {"real", "brl"}:
                        continue
                    period_start = _date_text(row.get("DT_INI_EXERC")) if flow_statement else ""
                    period_end = _date_text(row.get("DT_FIM_EXERC"))
                    if flow_statement and period_start != f"{year}-01-01":
                        continue
                    if not period_end.startswith(f"{year}-"):
                        continue
                    try:
                        version = int(str(row.get("VERSAO") or "1").strip())
                    except ValueError:
                        version = 1
                    observations.append(
                        CVMIncomeObservation(
                            year=year,
                            document_type=doc.upper(),
                            period_start=period_start,
                            period_end=period_end,
                            reference_date=_date_text(row.get("DT_REFER")) or None,
                            version=version,
                            value_mbrl=_to_mbrl(row.get("VL_CONTA"), row.get("ESCALA_MOEDA")),
                            account_code=account_code,
                            account_label=str(row.get("DS_CONTA") or "").strip() or None,
                            statement=statement_upper,
                        )
                    )

    latest: dict[tuple[str, str], CVMIncomeObservation] = {}
    for item in observations:
        key = (item.account_code, item.period_end)
        existing = latest.get(key)
        if existing is None or item.version > existing.version:
            latest[key] = item
        elif item.version == existing.version and abs(item.value_mbrl - existing.value_mbrl) > 1e-9:
            raise ValueError(
                f"Motstridende CVM-verdier for {doc.upper()} {statement_upper} "
                f"{item.account_code} {item.period_end} v{item.version}"
            )
    return [latest[key] for key in sorted(latest)]


def parse_dre_accounts_archive(
    payload: bytes,
    *,
    year: int,
    document_type: str,
    account_codes: set[str] | None = None,
) -> list[CVMIncomeObservation]:
    """Read Bemobi consolidated DRE accounts, keeping only year-to-date rows."""
    wanted = account_codes or {item["account"] for item in DRE_METRICS.values()}
    return parse_statement_accounts_archive(
        payload,
        year=year,
        document_type=document_type,
        statement="DRE",
        account_codes=wanted,
    )


def parse_parent_net_income_archive(
    payload: bytes,
    *,
    year: int,
    document_type: str,
) -> list[CVMIncomeObservation]:
    """Compatibility wrapper for the original payout-model parser."""
    return parse_dre_accounts_archive(
        payload,
        year=year,
        document_type=document_type,
        account_codes={PARENT_NET_INCOME_ACCOUNT},
    )


def _derive_metric_quarters(
    *,
    year: int,
    observations: list[CVMIncomeObservation],
) -> dict[str, tuple[float, list[CVMIncomeObservation], str]]:
    itr = {
        item.period_end: item
        for item in observations
        if item.year == year and item.document_type == "ITR"
    }
    dfp = {
        item.period_end: item
        for item in observations
        if item.year == year and item.document_type == "DFP"
    }
    ends = {
        "1Q": f"{year}-03-31",
        "2Q": f"{year}-06-30",
        "3Q": f"{year}-09-30",
        "4Q": f"{year}-12-31",
    }
    result: dict[str, tuple[float, list[CVMIncomeObservation], str]] = {}
    q1 = itr.get(ends["1Q"])
    q2_ytd = itr.get(ends["2Q"])
    q3_ytd = itr.get(ends["3Q"])
    fy = dfp.get(ends["4Q"])
    if q1 is not None:
        result["1Q"] = (q1.value_mbrl, [q1], "CVM ITR")
    if q1 is not None and q2_ytd is not None:
        result["2Q"] = (q2_ytd.value_mbrl - q1.value_mbrl, [q1, q2_ytd], "CVM ITR")
    if q2_ytd is not None and q3_ytd is not None:
        result["3Q"] = (q3_ytd.value_mbrl - q2_ytd.value_mbrl, [q2_ytd, q3_ytd], "CVM ITR")
    if q3_ytd is not None and fy is not None:
        result["4Q"] = (fy.value_mbrl - q3_ytd.value_mbrl, [q3_ytd, fy], "CVM DFP / ITR")
    return result


def _derive_point_in_time_quarters(
    *,
    year: int,
    observations: list[CVMIncomeObservation],
) -> dict[str, tuple[float, list[CVMIncomeObservation], str]]:
    by_end = {
        item.period_end: item
        for item in observations
        if item.year == year
    }
    result: dict[str, tuple[float, list[CVMIncomeObservation], str]] = {}
    for label, end in (
        ("1Q", f"{year}-03-31"),
        ("2Q", f"{year}-06-30"),
        ("3Q", f"{year}-09-30"),
        ("4Q", f"{year}-12-31"),
    ):
        item = by_end.get(end)
        if item is None:
            continue
        source = "CVM DFP" if item.document_type == "DFP" else "CVM ITR"
        result[label] = (item.value_mbrl, [item], source)
    return result


def _add_metric_payload(
    result: dict[str, dict[str, Any]],
    *,
    year: int,
    field: str,
    account: str,
    derived: dict[str, tuple[float, list[CVMIncomeObservation], str]],
    quality: str,
) -> None:
    yy = str(year)[-2:]
    prefix = field.removesuffix("_mbrl")
    for label, (value, source_items, source) in derived.items():
        period = f"{label}{yy}"
        payload = result.setdefault(period, {"period": period})
        latest_version = max(item.version for item in source_items)
        payload[field] = round(value, 6)
        payload[f"{prefix}_source"] = source
        payload[f"{prefix}_source_url"] = (
            CVM_DFP_URL.format(year=year) if label == "4Q" else CVM_ITR_URL.format(year=year)
        )
        payload[f"{prefix}_quality"] = quality
        payload[f"{prefix}_account"] = account
        payload[f"{prefix}_as_of_date"] = source_items[-1].period_end
        payload[f"{prefix}_version"] = latest_version


def derive_standardized_dre_quarters(
    *,
    year: int,
    itr_observations: list[CVMIncomeObservation],
    dfp_observations: list[CVMIncomeObservation] | None = None,
) -> dict[str, dict[str, Any]]:
    """Derive standalone quarterly statutory revenue, EBIT and parent net income."""
    combined = [*itr_observations, *(dfp_observations or [])]
    result: dict[str, dict[str, Any]] = {}
    for field, definition in DRE_METRICS.items():
        account = definition["account"]
        metric_rows = [item for item in combined if item.account_code == account]
        _add_metric_payload(
            result,
            year=year,
            field=field,
            account=account,
            derived=_derive_metric_quarters(year=year, observations=metric_rows),
            quality="CVM_OFFICIAL_DRE_CON",
        )
    return result


def derive_reported_quarters(
    *,
    year: int,
    itr_observations: list[CVMIncomeObservation],
    dfp_observations: list[CVMIncomeObservation] | None = None,
) -> dict[str, dict[str, Any]]:
    """Backward-compatible parent-net-income-only quarterly derivation."""
    full = derive_standardized_dre_quarters(
        year=year,
        itr_observations=itr_observations,
        dfp_observations=dfp_observations,
    )
    keep = {
        "period",
        "reported_net_income_parent_mbrl",
        "reported_net_income_parent_source",
        "reported_net_income_parent_source_url",
        "reported_net_income_parent_quality",
        "reported_net_income_parent_account",
        "reported_net_income_parent_as_of_date",
        "reported_net_income_parent_version",
    }
    return {
        period: {key: value for key, value in payload.items() if key in keep}
        for period, payload in full.items()
        if payload.get("reported_net_income_parent_mbrl") is not None
    }


def derive_standardized_cashflow_quarters(
    *,
    year: int,
    itr_observations: list[CVMIncomeObservation],
    dfp_observations: list[CVMIncomeObservation] | None = None,
) -> dict[str, dict[str, Any]]:
    combined = [*itr_observations, *(dfp_observations or [])]
    result: dict[str, dict[str, Any]] = {}
    for field, definition in DFC_METRICS.items():
        account = definition["account"]
        metric_rows = [item for item in combined if item.account_code == account]
        _add_metric_payload(
            result,
            year=year,
            field=field,
            account=account,
            derived=_derive_metric_quarters(year=year, observations=metric_rows),
            quality="CVM_OFFICIAL_DFC_CON",
        )
    return result


def derive_standardized_balance_quarters(
    *,
    year: int,
    itr_bpa: list[CVMIncomeObservation],
    itr_bpp: list[CVMIncomeObservation],
    dfp_bpa: list[CVMIncomeObservation] | None = None,
    dfp_bpp: list[CVMIncomeObservation] | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for field, definition in BPA_METRICS.items():
        rows = [
            item
            for item in [*itr_bpa, *(dfp_bpa or [])]
            if item.account_code == definition["account"]
        ]
        _add_metric_payload(
            result,
            year=year,
            field=field,
            account=definition["account"],
            derived=_derive_point_in_time_quarters(year=year, observations=rows),
            quality="CVM_OFFICIAL_BPA_CON",
        )
    for field, definition in BPP_METRICS.items():
        rows = [
            item
            for item in [*itr_bpp, *(dfp_bpp or [])]
            if item.account_code == definition["account"]
        ]
        _add_metric_payload(
            result,
            year=year,
            field=field,
            account=definition["account"],
            derived=_derive_point_in_time_quarters(year=year, observations=rows),
            quality="CVM_OFFICIAL_BPP_CON",
        )

    for payload in result.values():
        current = payload.get("reported_borrowings_current_mbrl")
        noncurrent = payload.get("reported_borrowings_noncurrent_mbrl")
        cash = payload.get("reported_cash_mbrl")
        if current is not None and noncurrent is not None:
            borrowings = float(current) + float(noncurrent)
            payload["reported_borrowings_mbrl"] = round(borrowings, 6)
            if cash is not None:
                payload["reported_net_debt_mbrl"] = round(borrowings - float(cash), 6)
                payload["reported_net_debt_method"] = "CVM_BORROWINGS_MINUS_CASH"
    return result


def _merge_period_payloads(
    target: dict[str, dict[str, Any]],
    source: dict[str, dict[str, Any]],
) -> None:
    for period, payload in source.items():
        target.setdefault(period, {"period": period}).update(
            {key: value for key, value in payload.items() if key != "period"}
        )


async def _download_optional(
    url: str,
    *,
    label: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> bytes | None:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    response = await fetcher(
        url,
        headers={
            "Accept": "application/zip,application/octet-stream,*/*;q=0.8",
            "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
        },
    )
    status = int(getattr(response, "status", 0) or 0)
    if status == 404:
        return None
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(f"{label} feilet med HTTP {status or 'unknown'}")
    return await read_response_bytes(response, max_bytes=MAX_DOWNLOAD_BYTES, label=label)


async def _runtime_value(repository, key: str) -> str | None:
    row = await repository.first("SELECT value FROM runtime_state WHERE key=? LIMIT 1", (key,))
    return str(row["value"]) if row and row.get("value") else None


async def _set_runtime_value(repository, key: str, value: str) -> None:
    await repository.run(
        """
        INSERT INTO runtime_state(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (key, value),
    )


async def _latest_quarters_missing_reported(repository) -> bool:
    rows = await repository.all(
        """
        SELECT payload_json
        FROM bemobi_investor_facts
        WHERE fact_type='TTM_QUARTER'
        ORDER BY COALESCE(as_of_date, published_date, '') DESC, id DESC
        LIMIT 4
        """
    )
    if len(rows) < 4:
        return True
    for row in rows:
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            return True
        if any(payload.get(field) is None for field in _REQUIRED_QUARTER_FIELDS):
            return True
    return False


async def _refresh_due(repository, *, target_date: str) -> tuple[bool, str]:
    today = date.fromisoformat(target_date)
    missing = await _latest_quarters_missing_reported(repository)
    last_key = _LAST_ATTEMPT_KEY if missing else _LAST_SUCCESS_KEY
    last = await _runtime_value(repository, last_key)
    if not last:
        return True, "reported_quarters_missing" if missing else "never_refreshed"
    try:
        last_day = date.fromisoformat(last[:10])
    except ValueError:
        return True, "invalid_refresh_state"
    interval = MISSING_QUARTER_RETRY_DAYS if missing else NORMAL_REFRESH_DAYS
    if today - last_day >= timedelta(days=interval):
        return True, "reported_quarters_missing" if missing else "scheduled_refresh"
    return False, "retry_interval_not_due" if missing else "weekly_refresh_not_due"


async def _needs_previous_year(repository, year: int) -> bool:
    suffix = str(year)[-2:]
    keys = (f"3Q{suffix}", f"4Q{suffix}")
    for key in keys:
        row = await repository.first(
            """
            SELECT payload_json FROM bemobi_investor_facts
            WHERE fact_type='TTM_QUARTER' AND fact_key=? LIMIT 1
            """,
            (key,),
        )
        if row is None:
            continue
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            return True
        if any(payload.get(field) is None for field in _REQUIRED_QUARTER_FIELDS):
            return True
    return False


async def _merge_quarter_fact(repository, quarter: dict[str, Any]) -> str:
    key = str(quarter["period"])
    row = await repository.first(
        """
        SELECT id, payload_json FROM bemobi_investor_facts
        WHERE fact_type='TTM_QUARTER' AND fact_key=? LIMIT 1
        """,
        (key,),
    )
    if row is None:
        return "fact_missing"
    payload = json.loads(str(row.get("payload_json") or "{}"))
    changed = any(payload.get(field) != value for field, value in quarter.items() if field != "period")
    if not changed:
        return "unchanged"
    payload.update({field: value for field, value in quarter.items() if field != "period"})
    await repository.run(
        """
        UPDATE bemobi_investor_facts
        SET payload_json=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=?
        """,
        (json.dumps(payload, ensure_ascii=False, sort_keys=True), int(row["id"])),
    )
    return "updated"


def _parse_year_financials(
    *,
    year: int,
    itr_payload: bytes,
    dfp_payload: bytes | None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    itr_dre = parse_dre_accounts_archive(
        itr_payload,
        year=year,
        document_type="itr",
    )
    dfp_dre = (
        parse_dre_accounts_archive(dfp_payload, year=year, document_type="dfp")
        if dfp_payload is not None
        else []
    )
    _merge_period_payloads(
        result,
        derive_standardized_dre_quarters(
            year=year,
            itr_observations=itr_dre,
            dfp_observations=dfp_dre,
        ),
    )

    itr_dfc = parse_statement_accounts_archive(
        itr_payload,
        year=year,
        document_type="itr",
        statement="DFC",
        account_codes={item["account"] for item in DFC_METRICS.values()},
    )
    dfp_dfc = (
        parse_statement_accounts_archive(
            dfp_payload,
            year=year,
            document_type="dfp",
            statement="DFC",
            account_codes={item["account"] for item in DFC_METRICS.values()},
        )
        if dfp_payload is not None
        else []
    )
    _merge_period_payloads(
        result,
        derive_standardized_cashflow_quarters(
            year=year,
            itr_observations=itr_dfc,
            dfp_observations=dfp_dfc,
        ),
    )

    itr_bpa = parse_statement_accounts_archive(
        itr_payload,
        year=year,
        document_type="itr",
        statement="BPA",
        account_codes={item["account"] for item in BPA_METRICS.values()},
    )
    itr_bpp = parse_statement_accounts_archive(
        itr_payload,
        year=year,
        document_type="itr",
        statement="BPP",
        account_codes={item["account"] for item in BPP_METRICS.values()},
    )
    dfp_bpa = (
        parse_statement_accounts_archive(
            dfp_payload,
            year=year,
            document_type="dfp",
            statement="BPA",
            account_codes={item["account"] for item in BPA_METRICS.values()},
        )
        if dfp_payload is not None
        else []
    )
    dfp_bpp = (
        parse_statement_accounts_archive(
            dfp_payload,
            year=year,
            document_type="dfp",
            statement="BPP",
            account_codes={item["account"] for item in BPP_METRICS.values()},
        )
        if dfp_payload is not None
        else []
    )
    _merge_period_payloads(
        result,
        derive_standardized_balance_quarters(
            year=year,
            itr_bpa=itr_bpa,
            itr_bpp=itr_bpp,
            dfp_bpa=dfp_bpa,
            dfp_bpp=dfp_bpp,
        ),
    )
    return result


async def refresh_bemobi_reported_net_income(
    repository,
    *,
    target_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh Bemobi standardized consolidated financials from CVM ITR/DFP.

    The established function name is retained for compatibility. It now refreshes statutory
    revenue, EBIT, parent net income, operating cash flow, cash and borrowings. This lets the
    Bemobi dashboard progressively replace curated accounting facts while keeping adjusted
    KPIs sourced from the official result release.
    """
    due, reason = await _refresh_due(repository, target_date=target_date)
    if not due:
        return {"status": "skipped", "reason": reason, "rows_written": 0, "errors": []}

    await _set_runtime_value(repository, _LAST_ATTEMPT_KEY, target_date)
    current_year = date.fromisoformat(target_date).year
    previous_year = current_year - 1
    years: list[int] = [current_year]
    if await _needs_previous_year(repository, previous_year):
        years.insert(0, previous_year)

    derived: dict[str, dict[str, Any]] = {}
    archives: list[str] = []
    unavailable: list[str] = []
    errors: list[dict[str, Any]] = []

    for year in years:
        itr_payload: bytes | None = None
        dfp_payload: bytes | None = None
        itr_url = CVM_ITR_URL.format(year=year)
        try:
            itr_payload = await _download_optional(
                itr_url,
                label=f"CVM ITR {year}",
                fetcher=fetcher,
            )
            if itr_payload is None:
                unavailable.append(f"ITR {year}")
            else:
                archives.append(f"ITR {year}")
        except Exception as exc:
            errors.append({"archive": f"ITR {year}", "error": str(exc)[:1000]})

        need_dfp = year == previous_year
        if need_dfp:
            dfp_url = CVM_DFP_URL.format(year=year)
            try:
                dfp_payload = await _download_optional(
                    dfp_url,
                    label=f"CVM DFP {year}",
                    fetcher=fetcher,
                )
                if dfp_payload is None:
                    unavailable.append(f"DFP {year}")
                else:
                    archives.append(f"DFP {year}")
            except Exception as exc:
                errors.append({"archive": f"DFP {year}", "error": str(exc)[:1000]})

        if itr_payload is None:
            continue
        try:
            _merge_period_payloads(
                derived,
                _parse_year_financials(
                    year=year,
                    itr_payload=itr_payload,
                    dfp_payload=dfp_payload,
                ),
            )
        except Exception as exc:
            errors.append({"archive": f"FINANCIALS {year}", "error": str(exc)[:1000]})

    statuses: dict[str, str] = {}
    for period, quarter in sorted(derived.items()):
        try:
            statuses[period] = await _merge_quarter_fact(repository, quarter)
        except Exception as exc:
            errors.append({"period": period, "error": str(exc)[:1000]})

    rows_written = sum(1 for status in statuses.values() if status == "updated")
    if not errors:
        await _set_runtime_value(repository, _LAST_SUCCESS_KEY, target_date)
    status = "error" if errors and not derived else ("partial" if errors else "ok")
    return {
        "status": status,
        "reason": reason,
        "years": years,
        "archives": archives,
        "unavailable": unavailable,
        "derived_periods": sorted(derived),
        "metrics": {
            "DRE": {field: definition["account"] for field, definition in DRE_METRICS.items()},
            "DFC": {field: definition["account"] for field, definition in DFC_METRICS.items()},
            "BPA": {field: definition["account"] for field, definition in BPA_METRICS.items()},
            "BPP": {field: definition["account"] for field, definition in BPP_METRICS.items()},
        },
        "fact_status": statuses,
        "rows_written": rows_written,
        "normal_refresh_days": NORMAL_REFRESH_DAYS,
        "missing_quarter_retry_days": MISSING_QUARTER_RETRY_DAYS,
        "errors": errors,
    }

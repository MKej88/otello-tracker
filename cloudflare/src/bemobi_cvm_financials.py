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
CAPEX_FIELD = "reported_capex_cash_outflow_mbrl"
CAPEX_SELECTION = "CVM_DFC_DESCRIPTION_MATCH"
# CVM account numbering for this line is issuer/filing dependent. Bemobi used 6.02.02
# historically and 6.02.10 in 2Q26, so capex must be identified from DS_CONTA rather
# than a fixed CD_CONTA.
CAPEX_ACTION_TOKENS = ("aquisicao", "adicao", "adicoes")
CAPEX_ASSET_TOKENS = ("imobilizado", "intangivel")

# Capex is a reconciliation metric, not a hard blocker for the core accounting refresh.
_REQUIRED_QUARTER_FIELDS = tuple([*DRE_METRICS, *DFC_METRICS, *BPA_METRICS, *BPP_METRICS])


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
        preferred = [
            f"{doc}_cia_aberta_dfc_mi_con_{year}.csv",
            f"{doc}_cia_aberta_dfc_md_con_{year}.csv",
        ]
        members = {name.rsplit("/", 1)[-1].lower(): name for name in archive.namelist()}
        for expected in preferred:
            if expected in members:
                return members[expected]
        raise ValueError(f"CVM {document_type.upper()} {year} mangler konsolidert DFC")

    expected = f"{doc}_cia_aberta_{statement.lower()}_con_{year}.csv"
    matches = [
        name for name in archive.namelist()
        if name.rsplit("/", 1)[-1].lower() == expected
    ]
    if len(matches) != 1:
        raise ValueError(
            f"CVM {document_type.upper()} {year} forventet {expected}, fant {len(matches)}"
        )
    return matches[0]


def _row_to_observation(
    row: dict[str, str],
    *,
    year: int,
    document_type: str,
    statement: str,
) -> CVMIncomeObservation | None:
    flow_statement = statement in {"DRE", "DFC"}
    if _clean_cvm_code(row.get("CD_CVM")) != BEMOBI_CVM_CODE:
        return None
    if _norm(row.get("ORDEM_EXERC")) != "ultimo":
        return None
    if _norm(row.get("MOEDA")) not in {"real", "brl"}:
        return None
    period_start = _date_text(row.get("DT_INI_EXERC")) if flow_statement else ""
    period_end = _date_text(row.get("DT_FIM_EXERC"))
    if flow_statement and period_start != f"{year}-01-01":
        return None
    if not period_end.startswith(f"{year}-"):
        return None
    try:
        version = int(str(row.get("VERSAO") or "1").strip())
    except ValueError:
        version = 1
    return CVMIncomeObservation(
        year=year,
        document_type=document_type.upper(),
        period_start=period_start,
        period_end=period_end,
        reference_date=_date_text(row.get("DT_REFER")) or None,
        version=version,
        value_mbrl=_to_mbrl(row.get("VL_CONTA"), row.get("ESCALA_MOEDA")),
        account_code=str(row.get("CD_CONTA") or "").strip(),
        account_label=str(row.get("DS_CONTA") or "").strip() or None,
        statement=statement,
    )


def _statement_reader(
    payload: bytes,
    *,
    year: int,
    document_type: str,
    statement: str,
):
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
    member = _statement_member(
        archive,
        document_type=doc,
        year=year,
        statement=statement_upper,
    )
    raw_member = archive.open(member, "r")
    buffered = io.BufferedReader(raw_member, buffer_size=64 * 1024)
    encoding = _csv_encoding(bytes(buffered.peek(8192)[:8192]))
    text_stream = io.TextIOWrapper(buffered, encoding=encoding, newline="")
    reader = csv.DictReader(text_stream, delimiter=";")
    missing = sorted(required - set(reader.fieldnames or []))
    if missing:
        text_stream.close()
        archive.close()
        raise ValueError(
            f"CVM {doc.upper()} {statement_upper} {year} mangler kolonner: {', '.join(missing)}"
        )
    return archive, text_stream, reader


def _dedupe_observations(
    observations: list[CVMIncomeObservation],
    *,
    label: str,
) -> list[CVMIncomeObservation]:
    latest: dict[tuple[str, str], CVMIncomeObservation] = {}
    for item in observations:
        key = (item.account_code, item.period_end)
        existing = latest.get(key)
        if existing is None or item.version > existing.version:
            latest[key] = item
        elif item.version == existing.version and abs(item.value_mbrl - existing.value_mbrl) > 1e-9:
            raise ValueError(
                f"Motstridende CVM-verdier for {label} {item.account_code} "
                f"{item.period_end} v{item.version}"
            )
    return [latest[key] for key in sorted(latest)]


def parse_statement_accounts_archive(
    payload: bytes,
    *,
    year: int,
    document_type: str,
    statement: str,
    account_codes: set[str],
) -> list[CVMIncomeObservation]:
    """Read selected standardized consolidated statement accounts for Bemobi."""
    statement_upper = statement.upper()
    observations: list[CVMIncomeObservation] = []
    archive, text_stream, reader = _statement_reader(
        payload,
        year=year,
        document_type=document_type,
        statement=statement_upper,
    )
    try:
        for row in reader:
            account_code = str(row.get("CD_CONTA") or "").strip()
            if account_code not in account_codes:
                continue
            item = _row_to_observation(
                row,
                year=year,
                document_type=document_type,
                statement=statement_upper,
            )
            if item is not None:
                observations.append(item)
    finally:
        text_stream.close()
        archive.close()
    return _dedupe_observations(
        observations,
        label=f"{document_type.upper()} {statement_upper}",
    )


def _is_capex_label(label: str | None) -> bool:
    normalized = _norm(label)
    has_action = any(token in normalized for token in CAPEX_ACTION_TOKENS)
    has_asset = any(token in normalized for token in CAPEX_ASSET_TOKENS)
    return has_action and has_asset


def _is_combined_capex_label(label: str | None) -> bool:
    normalized = _norm(label)
    return _is_capex_label(label) and all(token in normalized for token in CAPEX_ASSET_TOKENS)


def parse_capex_accounts_archive(
    payload: bytes,
    *,
    year: int,
    document_type: str,
) -> list[CVMIncomeObservation]:
    """Identify Bemobi capex from DFC descriptions instead of unstable account numbers.

    If a filing provides one combined acquisition-of-PPE-and-intangibles line, use that row.
    If the filing splits tangible and intangible acquisitions, sum the matching component rows.
    The latest CVM filing version wins for each period.
    """
    observations: list[CVMIncomeObservation] = []
    archive, text_stream, reader = _statement_reader(
        payload,
        year=year,
        document_type=document_type,
        statement="DFC",
    )
    try:
        for row in reader:
            if not _is_capex_label(row.get("DS_CONTA")):
                continue
            item = _row_to_observation(
                row,
                year=year,
                document_type=document_type,
                statement="DFC",
            )
            if item is not None:
                observations.append(item)
    finally:
        text_stream.close()
        archive.close()

    observations = _dedupe_observations(
        observations,
        label=f"{document_type.upper()} DFC capex",
    )
    by_period: dict[str, list[CVMIncomeObservation]] = {}
    for item in observations:
        by_period.setdefault(item.period_end, []).append(item)

    result: list[CVMIncomeObservation] = []
    for period_end, rows in sorted(by_period.items()):
        latest_version = max(item.version for item in rows)
        rows = [item for item in rows if item.version == latest_version]
        combined = [item for item in rows if _is_combined_capex_label(item.account_label)]
        selected = combined if combined else rows
        if combined:
            # A combined line is already the total; multiple identical combined rows are
            # tolerated only when they agree, otherwise fail closed instead of double counting.
            values = {round(item.value_mbrl, 9) for item in combined}
            if len(values) != 1:
                raise ValueError(f"Motstridende kombinerte CVM-capexlinjer for {period_end}")
            selected = [sorted(combined, key=lambda item: item.account_code)[0]]
        value = sum(item.value_mbrl for item in selected)
        codes = sorted({item.account_code for item in selected})
        labels = sorted({str(item.account_label or "") for item in selected if item.account_label})
        first = selected[0]
        result.append(
            CVMIncomeObservation(
                year=year,
                document_type=first.document_type,
                period_start=first.period_start,
                period_end=period_end,
                reference_date=first.reference_date,
                version=latest_version,
                value_mbrl=value,
                account_code="+".join(codes),
                account_label=" + ".join(labels),
                statement="DFC",
            )
        )
    return result


def parse_dre_accounts_archive(
    payload: bytes,
    *,
    year: int,
    document_type: str,
    account_codes: set[str] | None = None,
) -> list[CVMIncomeObservation]:
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
    by_end = {item.period_end: item for item in observations if item.year == year}
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
        payload[field] = round(value, 6)
        payload[f"{prefix}_source"] = source
        payload[f"{prefix}_source_url"] = (
            CVM_DFP_URL.format(year=year) if label == "4Q" else CVM_ITR_URL.format(year=year)
        )
        payload[f"{prefix}_quality"] = quality
        payload[f"{prefix}_account"] = account
        payload[f"{prefix}_as_of_date"] = source_items[-1].period_end
        payload[f"{prefix}_version"] = max(item.version for item in source_items)


def _add_capex_payload(
    result: dict[str, dict[str, Any]],
    *,
    year: int,
    derived: dict[str, tuple[float, list[CVMIncomeObservation], str]],
) -> None:
    yy = str(year)[-2:]
    prefix = CAPEX_FIELD.removesuffix("_mbrl")
    for label, (value, source_items, source) in derived.items():
        period = f"{label}{yy}"
        payload = result.setdefault(period, {"period": period})
        account_codes = sorted({code for item in source_items for code in item.account_code.split("+") if code})
        account_labels = sorted({str(item.account_label or "") for item in source_items if item.account_label})
        payload[CAPEX_FIELD] = round(value, 6)
        payload[f"{prefix}_source"] = source
        payload[f"{prefix}_source_url"] = (
            CVM_DFP_URL.format(year=year) if label == "4Q" else CVM_ITR_URL.format(year=year)
        )
        payload[f"{prefix}_quality"] = "CVM_OFFICIAL_DFC_CON"
        payload[f"{prefix}_account"] = "+".join(account_codes) or None
        payload[f"{prefix}_account_labels"] = account_labels
        payload[f"{prefix}_selection"] = CAPEX_SELECTION
        payload[f"{prefix}_as_of_date"] = source_items[-1].period_end
        payload[f"{prefix}_version"] = max(item.version for item in source_items)


def derive_standardized_dre_quarters(
    *,
    year: int,
    itr_observations: list[CVMIncomeObservation],
    dfp_observations: list[CVMIncomeObservation] | None = None,
) -> dict[str, dict[str, Any]]:
    combined = [*itr_observations, *(dfp_observations or [])]
    result: dict[str, dict[str, Any]] = {}
    for field, definition in DRE_METRICS.items():
        rows = [item for item in combined if item.account_code == definition["account"]]
        _add_metric_payload(
            result,
            year=year,
            field=field,
            account=definition["account"],
            derived=_derive_metric_quarters(year=year, observations=rows),
            quality="CVM_OFFICIAL_DRE_CON",
        )
    return result


def derive_reported_quarters(
    *,
    year: int,
    itr_observations: list[CVMIncomeObservation],
    dfp_observations: list[CVMIncomeObservation] | None = None,
) -> dict[str, dict[str, Any]]:
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
    itr_capex_observations: list[CVMIncomeObservation] | None = None,
    dfp_capex_observations: list[CVMIncomeObservation] | None = None,
) -> dict[str, dict[str, Any]]:
    combined = [*itr_observations, *(dfp_observations or [])]
    result: dict[str, dict[str, Any]] = {}
    for field, definition in DFC_METRICS.items():
        rows = [item for item in combined if item.account_code == definition["account"]]
        _add_metric_payload(
            result,
            year=year,
            field=field,
            account=definition["account"],
            derived=_derive_metric_quarters(year=year, observations=rows),
            quality="CVM_OFFICIAL_DFC_CON",
        )
    capex_rows = [*(itr_capex_observations or []), *(dfp_capex_observations or [])]
    if capex_rows:
        _add_capex_payload(
            result,
            year=year,
            derived=_derive_metric_quarters(year=year, observations=capex_rows),
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
            item for item in [*itr_bpa, *(dfp_bpa or [])]
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
            item for item in [*itr_bpp, *(dfp_bpp or [])]
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

    itr_dre = parse_dre_accounts_archive(itr_payload, year=year, document_type="itr")
    dfp_dre = (
        parse_dre_accounts_archive(dfp_payload, year=year, document_type="dfp")
        if dfp_payload is not None else []
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
    itr_capex = parse_capex_accounts_archive(
        itr_payload,
        year=year,
        document_type="itr",
    )
    if dfp_payload is not None:
        dfp_dfc = parse_statement_accounts_archive(
            dfp_payload,
            year=year,
            document_type="dfp",
            statement="DFC",
            account_codes={item["account"] for item in DFC_METRICS.values()},
        )
        dfp_capex = parse_capex_accounts_archive(
            dfp_payload,
            year=year,
            document_type="dfp",
        )
    else:
        dfp_dfc = []
        dfp_capex = []
    _merge_period_payloads(
        result,
        derive_standardized_cashflow_quarters(
            year=year,
            itr_observations=itr_dfc,
            dfp_observations=dfp_dfc,
            itr_capex_observations=itr_capex,
            dfp_capex_observations=dfp_capex,
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
    if dfp_payload is not None:
        dfp_bpa = parse_statement_accounts_archive(
            dfp_payload,
            year=year,
            document_type="dfp",
            statement="BPA",
            account_codes={item["account"] for item in BPA_METRICS.values()},
        )
        dfp_bpp = parse_statement_accounts_archive(
            dfp_payload,
            year=year,
            document_type="dfp",
            statement="BPP",
            account_codes={item["account"] for item in BPP_METRICS.values()},
        )
    else:
        dfp_bpa = []
        dfp_bpp = []
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

    The established function name is retained for compatibility. It refreshes statutory
    revenue, EBIT, parent net income, operating cash flow, dynamic-description capex, cash
    and borrowings while adjusted KPIs stay sourced from Bemobi's official result release.
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

        if year == previous_year:
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
            "CAPEX": {
                "field": CAPEX_FIELD,
                "selection": CAPEX_SELECTION,
                "description_tokens": [*CAPEX_ACTION_TOKENS, *CAPEX_ASSET_TOKENS],
            },
            "BPA": {field: definition["account"] for field, definition in BPA_METRICS.items()},
            "BPP": {field: definition["account"] for field, definition in BPP_METRICS.items()},
        },
        "fact_status": statuses,
        "rows_written": rows_written,
        "normal_refresh_days": NORMAL_REFRESH_DAYS,
        "missing_quarter_retry_days": MISSING_QUARTER_RETRY_DAYS,
        "errors": errors,
    }

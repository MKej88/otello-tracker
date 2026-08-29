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
_REQUIRED_COLUMNS = {
    "CD_CVM",
    "VERSAO",
    "MOEDA",
    "ESCALA_MOEDA",
    "ORDEM_EXERC",
    "DT_INI_EXERC",
    "DT_FIM_EXERC",
    "CD_CONTA",
    "VL_CONTA",
}


@dataclass(frozen=True)
class CVMIncomeObservation:
    year: int
    document_type: str
    period_start: str
    period_end: str
    reference_date: str | None
    version: int
    value_mbrl: float


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
    raise ValueError("Kunne ikke dekode CVM DRE CSV")


def _dre_member(archive: zipfile.ZipFile, *, document_type: str, year: int) -> str:
    expected = f"{document_type.lower()}_cia_aberta_dre_con_{year}.csv"
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


def parse_parent_net_income_archive(
    payload: bytes,
    *,
    year: int,
    document_type: str,
) -> list[CVMIncomeObservation]:
    """Read only Bemobi's consolidated DRE account 3.11.01 from an ITR/DFP ZIP."""
    doc = document_type.lower()
    if doc not in {"itr", "dfp"}:
        raise ValueError(f"Ukjent CVM dokumenttype: {document_type}")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"CVM {doc.upper()} {year} er ikke en gyldig ZIP") from exc

    observations: list[CVMIncomeObservation] = []
    with archive:
        member = _dre_member(archive, document_type=doc, year=year)
        with archive.open(member, "r") as raw_member:
            buffered = io.BufferedReader(raw_member, buffer_size=64 * 1024)
            encoding = _csv_encoding(bytes(buffered.peek(8192)[:8192]))
            with io.TextIOWrapper(buffered, encoding=encoding, newline="") as text_stream:
                reader = csv.DictReader(text_stream, delimiter=";")
                missing = sorted(_REQUIRED_COLUMNS - set(reader.fieldnames or []))
                if missing:
                    raise ValueError(
                        f"CVM {doc.upper()} {year} mangler kolonner: {', '.join(missing)}"
                    )
                for row in reader:
                    if _clean_cvm_code(row.get("CD_CVM")) != BEMOBI_CVM_CODE:
                        continue
                    if str(row.get("CD_CONTA") or "").strip() != PARENT_NET_INCOME_ACCOUNT:
                        continue
                    if _norm(row.get("ORDEM_EXERC")) != "ultimo":
                        continue
                    if _norm(row.get("MOEDA")) not in {"real", "brl"}:
                        continue
                    period_start = _date_text(row.get("DT_INI_EXERC"))
                    period_end = _date_text(row.get("DT_FIM_EXERC"))
                    if period_start != f"{year}-01-01" or not period_end.startswith(f"{year}-"):
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
                        )
                    )

    latest: dict[str, CVMIncomeObservation] = {}
    for item in observations:
        existing = latest.get(item.period_end)
        if existing is None or item.version > existing.version:
            latest[item.period_end] = item
        elif item.version == existing.version and abs(item.value_mbrl - existing.value_mbrl) > 1e-9:
            raise ValueError(
                f"Motstridende CVM-verdier for {doc.upper()} {item.period_end} v{item.version}"
            )
    return [latest[key] for key in sorted(latest)]


def derive_reported_quarters(
    *,
    year: int,
    itr_observations: list[CVMIncomeObservation],
    dfp_observations: list[CVMIncomeObservation] | None = None,
) -> dict[str, dict[str, Any]]:
    """Derive standalone Q1–Q4 from CVM year-to-date ITR and full-year DFP values."""
    itr = {item.period_end: item for item in itr_observations if item.year == year}
    dfp = {item.period_end: item for item in (dfp_observations or []) if item.year == year}
    yy = str(year)[-2:]
    ends = {
        "1Q": f"{year}-03-31",
        "2Q": f"{year}-06-30",
        "3Q": f"{year}-09-30",
        "4Q": f"{year}-12-31",
    }
    result: dict[str, dict[str, Any]] = {}

    q1 = itr.get(ends["1Q"])
    q2_ytd = itr.get(ends["2Q"])
    q3_ytd = itr.get(ends["3Q"])
    fy = dfp.get(ends["4Q"])

    def add(label: str, value: float, source_items: list[CVMIncomeObservation], source: str) -> None:
        latest_version = max(item.version for item in source_items)
        result[f"{label}{yy}"] = {
            "period": f"{label}{yy}",
            "reported_net_income_parent_mbrl": round(value, 6),
            "reported_net_income_parent_source": source,
            "reported_net_income_parent_source_url": (
                CVM_DFP_URL.format(year=year) if label == "4Q" else CVM_ITR_URL.format(year=year)
            ),
            "reported_net_income_parent_quality": "CVM_OFFICIAL_DRE_CON",
            "reported_net_income_parent_account": PARENT_NET_INCOME_ACCOUNT,
            "reported_net_income_parent_as_of_date": source_items[-1].period_end,
            "reported_net_income_parent_version": latest_version,
        }

    if q1 is not None:
        add("1Q", q1.value_mbrl, [q1], "CVM ITR")
    if q1 is not None and q2_ytd is not None:
        add("2Q", q2_ytd.value_mbrl - q1.value_mbrl, [q1, q2_ytd], "CVM ITR")
    if q2_ytd is not None and q3_ytd is not None:
        add("3Q", q3_ytd.value_mbrl - q2_ytd.value_mbrl, [q2_ytd, q3_ytd], "CVM ITR")
    if q3_ytd is not None and fy is not None:
        add("4Q", fy.value_mbrl - q3_ytd.value_mbrl, [q3_ytd, fy], "CVM DFP / ITR")
    return result


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
        if payload.get("reported_net_income_parent_mbrl") is None:
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
        if payload.get("reported_net_income_parent_mbrl") is None:
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


async def refresh_bemobi_reported_net_income(
    repository,
    *,
    target_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh statutory parent net income used by the Bemobi payout run-rate model."""
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
            itr = parse_parent_net_income_archive(itr_payload, year=year, document_type="itr")
            dfp = (
                parse_parent_net_income_archive(dfp_payload, year=year, document_type="dfp")
                if dfp_payload is not None
                else []
            )
            derived.update(derive_reported_quarters(year=year, itr_observations=itr, dfp_observations=dfp))
        except Exception as exc:
            errors.append({"archive": f"DRE {year}", "error": str(exc)[:1000]})

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
        "fact_status": statuses,
        "rows_written": rows_written,
        "normal_refresh_days": NORMAL_REFRESH_DAYS,
        "missing_quarter_retry_days": MISSING_QUARTER_RETRY_DAYS,
        "errors": errors,
    }

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import unicodedata
import urllib.parse
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Awaitable, Callable, Iterable

try:
    from .bounded_response import read_response_bytes
except ImportError:
    from bounded_response import read_response_bytes

CVM_IPE_URL = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/"
    "ipe_cia_aberta_{year}.zip"
)
BEMOBI_CNPJ = "09.042.817/0001-05"
BEMOBI_CVM_CODE = "25500"
BEMOBI_FIRST_PUBLIC_YEAR = 2021
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
PREVIOUS_YEAR_REFRESH_DAYS = 30
_LAST_SUCCESS_PREFIX = "cvm_ipe_last_success:"
_REQUIRED_COLUMNS = {
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
}
_SPACE_RE = re.compile(r"\s+")
_JCP_RE = re.compile(r"juros sobre (?:o )?capital proprio")


@dataclass(frozen=True)
class CVMIPERecord:
    archive_year: int
    cnpj: str
    company_name: str
    cvm_code: str
    reference_date: str
    category: str
    document_type: str
    species: str
    subject: str
    delivery_date: str
    presentation_type: str
    protocol: str
    version: str
    download_url: str

    @property
    def version_number(self) -> int:
        try:
            return int(self.version or "1")
        except ValueError:
            return 1

    @property
    def logical_key(self) -> str:
        payload = "|".join(
            _norm(value)
            for value in (
                self.cnpj,
                self.reference_date,
                self.category,
                self.document_type,
                self.species,
                self.subject,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def external_id(self) -> str:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.download_url).query)
        download_protocol = (query.get("numProtocolo") or [""])[0]
        sequence = (query.get("numSequencia") or [""])[0]
        source_key = self.protocol or f"download-{download_protocol}-{sequence}"
        if not source_key.strip("-"):
            canonical = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
            source_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return (
            f"cvm-ipe:{self.archive_year}:{source_key}:"
            f"{download_protocol or 'na'}-{sequence or 'na'}:"
            f"v{self.version_number}:{self.logical_key[:12]}"
        )


def _norm(value: str | None) -> str:
    text = html.unescape(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return _SPACE_RE.sub(" ", text.lower()).strip()


def _clean(value: str | None) -> str:
    return _SPACE_RE.sub(" ", html.unescape(value or "")).strip()


def _mentions_jcp(text: str) -> bool:
    return _JCP_RE.search(text) is not None or re.search(r"\bjcp\b", text) is not None


def _decode_csv(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Kunne ikke dekode CVM IPE CSV")


def parse_cvm_ipe_archive(payload: bytes, *, year: int) -> list[CVMIPERecord]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"CVM IPE {year} er ikke en gyldig ZIP") from exc

    with archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"CVM IPE {year} forventet én CSV, fant {len(members)}")
        text = _decode_csv(archive.read(members[0]))

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    missing = sorted(_REQUIRED_COLUMNS - set(reader.fieldnames or []))
    if missing:
        raise ValueError(f"CVM IPE {year} mangler kolonner: {', '.join(missing)}")

    result: list[CVMIPERecord] = []
    for row in reader:
        if _clean(row.get("CNPJ_Companhia")) != BEMOBI_CNPJ:
            continue
        if _clean(row.get("Codigo_CVM")) != BEMOBI_CVM_CODE:
            continue
        result.append(
            CVMIPERecord(
                archive_year=year,
                cnpj=_clean(row.get("CNPJ_Companhia")),
                company_name=_clean(row.get("Nome_Companhia")),
                cvm_code=_clean(row.get("Codigo_CVM")),
                reference_date=_clean(row.get("Data_Referencia")),
                category=_clean(row.get("Categoria")),
                document_type=_clean(row.get("Tipo")),
                species=_clean(row.get("Especie")),
                subject=_clean(row.get("Assunto")),
                delivery_date=_clean(row.get("Data_Entrega")),
                presentation_type=_clean(row.get("Tipo_Apresentacao")),
                protocol=_clean(row.get("Protocolo_Entrega")),
                version=_clean(row.get("Versao")),
                download_url=_clean(row.get("Link_Download")),
            )
        )
    return result


def _is_relevant(record: CVMIPERecord) -> bool:
    category = _norm(record.category)
    document_type = _norm(record.document_type)
    species = _norm(record.species)
    subject = _norm(record.subject)
    if category in {
        "fato relevante",
        "comunicado ao mercado",
        "aviso aos acionistas",
        "relatorio proventos",
        "calendario de eventos corporativos",
        "reuniao da administracao",
    }:
        return True
    if category == "dados economico-financeiros":
        return any(
            term in document_type
            for term in (
                "press-release",
                "demonstracoes financeiras intermediarias",
                "demonstracoes financeiras anuais completas",
            )
        )
    if category == "assembleia":
        important = (
            "dividend",
            "jcp",
            "recompra",
            "aumento de capital",
            "reducao de capital",
            "cancelamento de acoes",
            "aquisicao",
            "fusao",
            "incorporacao",
        )
        return species == "ata" or _mentions_jcp(subject) or any(term in subject for term in important)
    return False


def classify_cvm_record(record: CVMIPERecord) -> tuple[str, bool, str]:
    category = _norm(record.category)
    document_type = _norm(record.document_type)
    subject = _norm(record.subject)
    combined = " | ".join((category, document_type, _norm(record.species), subject))

    if (
        category == "dados economico-financeiros"
        and any(
            term in document_type
            for term in (
                "press-release",
                "demonstracoes financeiras intermediarias",
                "demonstracoes financeiras anuais completas",
            )
        )
    ) or "apresentacao de resultados" in subject:
        return "RESULTS", False, "CVM result/report metadata"
    if any(term in combined for term in ("programa de recompra", "recompra de acoes", "recompra")):
        return "BUYBACK", False, "CVM metadata explicitly mentions share buyback"
    if any(
        term in subject
        for term in (
            "aquisicao de 100%",
            "aquisicao da ",
            "aquisicao do ",
            "aquisicao de ",
            "fusao",
            "incorporacao",
            "alienacao de ativo",
            "alienacao de subsidiaria",
        )
    ):
        return "M_AND_A", False, "CVM subject explicitly describes a business transaction"
    has_jcp = _mentions_jcp(combined)
    has_dividend = "dividend" in combined
    if has_jcp:
        if has_dividend:
            return "JCP", True, "CVM metadata mentions both dividend and JCP; review required"
        return "JCP", False, "CVM metadata explicitly mentions JCP"
    if has_dividend:
        return "DIVIDEND", False, "CVM metadata explicitly mentions dividend"
    if category == "relatorio proventos":
        return "OTHER", True, "CVM proventos report lacks safe subtype metadata"
    if any(
        term in combined
        for term in (
            "aumento de capital",
            "reducao de capital",
            "cancelamento de acoes",
            "capital social",
            "grupamento de acoes",
            "desdobramento de acoes",
        )
    ):
        return "CAPITAL", False, "CVM metadata explicitly mentions capital/share-count action"
    if any(term in combined for term in ("guidance", "projecoes", "projecao", "estimativas financeiras")):
        return "GUIDANCE", False, "CVM metadata explicitly mentions guidance/projections"
    if category in {
        "comunicado ao mercado",
        "reuniao da administracao",
        "assembleia",
        "calendario de eventos corporativos",
    }:
        return "CORPORATE", False, "CVM corporate/governance metadata"
    if category in {"fato relevante", "aviso aos acionistas"}:
        return "OTHER", True, "Potentially material CVM filing without safe metadata-only subtype"
    return "OTHER", True, "No high-confidence CVM metadata rule"


def _nav_impact(category: str) -> str:
    return "POTENTIAL" if category in {
        "DIVIDEND", "JCP", "BUYBACK", "M_AND_A", "CAPITAL", "GUIDANCE"
    } else "NONE"


def _headline(record: CVMIPERecord) -> str:
    detail = record.subject or record.document_type or record.species
    return f"{record.category} — {detail}" if detail else record.category


def _row_hash(record: CVMIPERecord) -> str:
    canonical = json.dumps(asdict(record), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _latest_versions(records: Iterable[CVMIPERecord]) -> dict[str, int]:
    latest: dict[str, int] = {}
    for record in records:
        latest[record.logical_key] = max(latest.get(record.logical_key, 0), record.version_number)
    return latest


async def _download_year(
    year: int,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> bytes:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    url = CVM_IPE_URL.format(year=year)
    response = await fetcher(
        url,
        headers={
            "Accept": "application/zip,application/octet-stream,*/*;q=0.8",
            "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
        },
    )
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(f"CVM IPE {year} feilet med HTTP {getattr(response, 'status', 'unknown')}")
    return await read_response_bytes(
        response,
        max_bytes=MAX_DOWNLOAD_BYTES,
        label=f"CVM IPE {year}",
    )


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


async def _year_has_archive(repository, year: int) -> bool:
    row = await repository.first(
        """
        SELECT 1 AS ok FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='CVM' AND sd.external_id LIKE ?
        LIMIT 1
        """,
        (f"cvm-ipe:{year}:%",),
    )
    return row is not None


async def years_due(repository, *, target_date: str) -> list[int]:
    today = date.fromisoformat(target_date)
    current = today.year
    selected: list[int] = []
    for year in range(BEMOBI_FIRST_PUBLIC_YEAR, current + 1):
        if year == current:
            selected.append(year)
            continue
        if not await _year_has_archive(repository, year):
            selected.append(year)
            continue
        if year == current - 1:
            last = await _runtime_value(repository, f"{_LAST_SUCCESS_PREFIX}{year}")
            if not last:
                selected.append(year)
                continue
            try:
                last_day = date.fromisoformat(last[:10])
            except ValueError:
                selected.append(year)
                continue
            if today - last_day >= timedelta(days=PREVIOUS_YEAR_REFRESH_DAYS):
                selected.append(year)
    return selected


async def _upsert_record(repository, record: CVMIPERecord, *, is_latest_version: bool) -> dict[str, Any]:
    category, review, reason = classify_cvm_record(record)
    processing_status = "IGNORED" if not is_latest_version else (
        "REVIEW_REQUIRED" if review else "PARSED"
    )
    metadata = {
        "source_quality": "OFFICIAL_REGULATOR_METADATA",
        "cvm_dataset": "CIA_ABERTA/DOC/IPE",
        "archive_year": record.archive_year,
        "cnpj": record.cnpj,
        "company_name": record.company_name,
        "cvm_code": record.cvm_code,
        "reference_date": record.reference_date,
        "cvm_category": record.category,
        "cvm_type": record.document_type,
        "cvm_species": record.species,
        "cvm_subject": record.subject,
        "delivery_date": record.delivery_date,
        "presentation_type": record.presentation_type,
        "protocol": record.protocol,
        "version": record.version_number,
        "logical_key": record.logical_key,
        "is_latest_version": is_latest_version,
        "classification_reason": reason,
        "requires_review": review,
        "hash_scope": "CVM_IPE_METADATA_ROW",
        "document_body_persisted": False,
        "financial_effect_applied": False,
        "workflow": "cloudflare_full_refresh",
    }
    document_id = await repository.create_source_document(
        source_code="CVM",
        external_id=record.external_id,
        document_type="CVM_IPE_METADATA",
        title=_headline(record),
        url=record.download_url,
        published_at=record.delivery_date or record.reference_date,
        content_sha256=_row_hash(record),
        metadata=metadata,
    )
    issuer_id = await repository.instrument_id("BMOB3")
    parts = [f"Categoria: {record.category}"]
    if record.document_type:
        parts.append(f"Tipo: {record.document_type}")
    if record.species:
        parts.append(f"Espécie: {record.species}")
    if record.subject:
        parts.append(f"Assunto: {record.subject}")
    notes = (
        f"CVM IPE metadata classification: {reason}. "
        "Linked filing content is not parsed or applied to NAV/cash automatically."
    )
    await repository.run(
        """
        INSERT INTO company_news(
            issuer_instrument_id, source_document_id, headline, published_at,
            category, nav_impact, processing_status, summary, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_document_id) DO UPDATE SET
            issuer_instrument_id=excluded.issuer_instrument_id,
            headline=excluded.headline,
            published_at=excluded.published_at,
            category=excluded.category,
            nav_impact=excluded.nav_impact,
            processing_status=excluded.processing_status,
            summary=excluded.summary,
            notes=excluded.notes,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (
            issuer_id,
            document_id,
            _headline(record),
            record.delivery_date or record.reference_date,
            category,
            _nav_impact(category),
            processing_status,
            " | ".join(parts),
            notes,
        ),
    )
    return {
        "source_document_id": document_id,
        "category": category,
        "requires_review": review,
        "is_latest_version": is_latest_version,
        "protocol": record.protocol,
        "version": record.version_number,
    }


async def refresh_bemobi_cvm(
    repository,
    *,
    target_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    selected = await years_due(repository, target_date=target_date)
    if not selected:
        return {
            "status": "ok",
            "years": [],
            "skipped": True,
            "reason": "cvm_archives_not_due",
            "errors": [],
        }

    archived: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    discovered = 0
    relevant = 0
    successful_years: list[int] = []
    for year in selected:
        try:
            payload = await _download_year(year, fetcher=fetcher)
            records = parse_cvm_ipe_archive(payload, year=year)
            discovered += len(records)
            relevant_records = [record for record in records if _is_relevant(record)]
            relevant += len(relevant_records)
            latest = _latest_versions(relevant_records)
            for record in relevant_records:
                archived.append(
                    await _upsert_record(
                        repository,
                        record,
                        is_latest_version=record.version_number == latest[record.logical_key],
                    )
                )
            successful_years.append(year)
            await _set_runtime_value(
                repository,
                f"{_LAST_SUCCESS_PREFIX}{year}",
                target_date,
            )
        except Exception as exc:
            errors.append({"year": year, "error": str(exc)[:1000]})

    categories = Counter(item["category"] for item in archived if item["is_latest_version"])
    status = "error" if errors and not successful_years else ("partial" if errors else "ok")
    return {
        "status": status,
        "years": selected,
        "successful_years": successful_years,
        "discovered_bemobi_rows": discovered,
        "relevant_rows": relevant,
        "archived": len(archived),
        "latest_versions": sum(1 for item in archived if item["is_latest_version"]),
        "requires_review": sum(
            1 for item in archived if item["is_latest_version"] and item["requires_review"]
        ),
        "categories": dict(sorted(categories.items())),
        "previous_year_refresh_days": PREVIOUS_YEAR_REFRESH_DAYS,
        "errors": errors,
    }

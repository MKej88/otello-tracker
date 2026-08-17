from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable

from app.db.connection import get_connection
from app.db.repository import create_source_document, instrument_id

CVM_IPE_URL = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/"
    "ipe_cia_aberta_{year}.zip"
)
BEMOBI_CNPJ = "09.042.817/0001-05"
BEMOBI_CVM_CODE = "25500"
BEMOBI_NAME = "BEMOBI MOBILE TECH S.A."
BEMOBI_FIRST_PUBLIC_YEAR = 2021
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
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
        # CVM's Protocolo_Entrega is not guaranteed to be unique across every metadata
        # row in an annual IPE archive. Include download identity, version and a short
        # logical-row fingerprint so distinct official rows can never overwrite each
        # other while exact reruns stay idempotent.
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
    """Parse the official CVM annual IPE ZIP and return only Bemobi rows."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"CVM IPE {year} er ikke en gyldig ZIP") from exc

    with archive:
        csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(csv_members) != 1:
            raise ValueError(f"CVM IPE {year} forventet én CSV, fant {len(csv_members)}")
        raw = archive.read(csv_members[0])

    text = _decode_csv(raw)
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    fields = set(reader.fieldnames or [])
    missing = sorted(_REQUIRED_COLUMNS - fields)
    if missing:
        raise ValueError(f"CVM IPE {year} mangler kolonner: {', '.join(missing)}")

    records: list[CVMIPERecord] = []
    for row in reader:
        if _clean(row.get("CNPJ_Companhia")) != BEMOBI_CNPJ:
            continue
        if _clean(row.get("Codigo_CVM")) != BEMOBI_CVM_CODE:
            continue
        records.append(
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
    return records


def download_cvm_ipe_year(year: int, *, timeout: int = 45, attempts: int = 3) -> bytes:
    url = CVM_IPE_URL.format(year=year)
    last_error: Exception | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "otello-tracker/1.0 private-investor-dashboard"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(payload) > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"CVM IPE {year} overstiger sikker størrelsesgrense")
            if not payload:
                raise ValueError(f"CVM IPE {year} returnerte tom fil")
            return payload
        except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
    raise RuntimeError(f"CVM IPE {year} kunne ikke lastes ned: {last_error}")


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


def classify_cvm_ipe_record(record: CVMIPERecord) -> tuple[str, bool, str]:
    """Conservative metadata classification; this function never creates NAV effects."""
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

    # Use subject, not a generic CVM document type, for M&A. A type such as
    # 'Aquisição/Alienação de Participação Acionária' often describes shareholder
    # ownership disclosures rather than a company acquisition.
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
            return "JCP", True, "CVM metadata mentions both dividend and JCP; subtype/content review required"
        return "JCP", False, "CVM metadata explicitly mentions JCP"
    if has_dividend:
        return "DIVIDEND", False, "CVM metadata explicitly mentions dividend"
    if category == "relatorio proventos":
        return "OTHER", True, "CVM proventos report lacks metadata needed to distinguish dividend from JCP"

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
        return "OTHER", True, "Potentially material CVM filing without a safe metadata-only subtype"

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


def _upsert_record(
    record: CVMIPERecord,
    *,
    is_latest_version: bool,
    database_path: str | None,
) -> dict[str, Any]:
    category, review, reason = classify_cvm_ipe_record(record)
    if not is_latest_version:
        processing_status = "IGNORED"
    else:
        processing_status = "REVIEW_REQUIRED" if review else "PARSED"

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
    }

    with get_connection(database_path) as connection:
        issuer_id = instrument_id(connection, "BMOB3")
        document_id = create_source_document(
            connection,
            source_code="CVM",
            external_id=record.external_id,
            document_type="CVM_IPE_METADATA",
            title=_headline(record),
            url=record.download_url,
            published_at=record.delivery_date or record.reference_date,
            content_sha256=_row_hash(record),
            metadata=metadata,
        )
        summary_parts = [f"Categoria: {record.category}"]
        if record.document_type:
            summary_parts.append(f"Tipo: {record.document_type}")
        if record.species:
            summary_parts.append(f"Espécie: {record.species}")
        if record.subject:
            summary_parts.append(f"Assunto: {record.subject}")
        notes = (
            f"CVM IPE metadata classification: {reason}. "
            "Linked filing content is not parsed or applied to NAV/cash automatically."
        )
        connection.execute(
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
                " | ".join(summary_parts),
                notes,
            ),
        )
        row = connection.execute(
            "SELECT id FROM company_news WHERE source_document_id = ?", (document_id,)
        ).fetchone()
        connection.commit()
    return {
        "source_document_id": document_id,
        "company_news_id": int(row["id"]),
        "category": category,
        "requires_review": review,
        "is_latest_version": is_latest_version,
        "protocol": record.protocol,
        "version": record.version_number,
    }


def _archived_years(database_path: str | None) -> set[int]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT sd.external_id
            FROM source_documents sd
            JOIN sources s ON s.id = sd.source_id
            WHERE s.code = 'CVM' AND sd.external_id LIKE 'cvm-ipe:%'
            """
        ).fetchall()
    years: set[int] = set()
    for row in rows:
        parts = str(row["external_id"]).split(":", 2)
        if len(parts) >= 2:
            try:
                years.add(int(parts[1]))
            except ValueError:
                pass
    return years


def years_for_refresh(database_path: str | None, *, target_year: int | None = None) -> list[int]:
    current = target_year or date.today().year
    desired = set(range(BEMOBI_FIRST_PUBLIC_YEAR, current + 1))
    archived = _archived_years(database_path)
    missing_historical = {year for year in desired if year < current - 1 and year not in archived}
    rolling = {year for year in (current - 1, current) if year >= BEMOBI_FIRST_PUBLIC_YEAR}
    return sorted(missing_historical | rolling)


def collect_bemobi_cvm_news(
    database_path: str | None = None,
    *,
    years: Iterable[int] | None = None,
    target_year: int | None = None,
    timeout: int = 45,
) -> dict[str, Any]:
    selected_years = list(years) if years is not None else years_for_refresh(
        database_path, target_year=target_year
    )
    archived: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    discovered = 0
    relevant = 0

    for year in selected_years:
        try:
            records = parse_cvm_ipe_archive(download_cvm_ipe_year(year, timeout=timeout), year=year)
            discovered += len(records)
            relevant_records = [record for record in records if _is_relevant(record)]
            relevant += len(relevant_records)
            latest = _latest_versions(relevant_records)
            for record in relevant_records:
                archived.append(
                    _upsert_record(
                        record,
                        is_latest_version=record.version_number == latest[record.logical_key],
                        database_path=database_path,
                    )
                )
        except Exception as exc:
            errors.append({"year": year, "error": str(exc)})

    categories = Counter(item["category"] for item in archived if item["is_latest_version"])
    return {
        "years": selected_years,
        "discovered_bemobi_rows": discovered,
        "relevant_rows": relevant,
        "archived": len(archived),
        "latest_versions": sum(1 for item in archived if item["is_latest_version"]),
        "requires_review": sum(
            1 for item in archived if item["is_latest_version"] and item["requires_review"]
        ),
        "categories": dict(sorted(categories.items())),
        "errors": errors,
    }


def bemobi_cvm_news_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT cn.published_at, cn.category, cn.processing_status, sd.metadata_json
            FROM company_news cn
            JOIN instruments i ON i.id = cn.issuer_instrument_id
            JOIN source_documents sd ON sd.id = cn.source_document_id
            JOIN sources s ON s.id = sd.source_id
            WHERE i.symbol = 'BMOB3' AND s.code = 'CVM'
              AND sd.external_id LIKE 'cvm-ipe:%'
            ORDER BY cn.published_at, cn.id
            """
        ).fetchall()
    if not rows:
        return {"status": "empty", "count": 0}

    latest_rows = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        if metadata.get("is_latest_version", True):
            latest_rows.append(row)
    categories = Counter(str(row["category"]) for row in latest_rows)
    years = Counter(str(row["published_at"])[:4] for row in latest_rows if row["published_at"])
    return {
        "status": "ok",
        "count": len(latest_rows),
        "all_versions": len(rows),
        "from": str(latest_rows[0]["published_at"])[:10] if latest_rows else None,
        "to": str(latest_rows[-1]["published_at"])[:10] if latest_rows else None,
        "requires_review": sum(
            row["processing_status"] == "REVIEW_REQUIRED" for row in latest_rows
        ),
        "by_year": dict(sorted(years.items())),
        "by_category": dict(sorted(categories.items())),
    }


def list_bemobi_news(
    database_path: str | None = None,
    *,
    limit: int = 50,
    category: str | None = None,
    include_superseded: bool = False,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 200))
    params: list[Any] = []
    category_sql = ""
    if category:
        category_sql = " AND cn.category = ?"
        params.append(category.upper())
    # Fetch extra rows because older CVM versions are filtered in Python by default.
    params.append(max(safe_limit * 4, 100))
    with get_connection(database_path) as connection:
        rows = connection.execute(
            f"""
            SELECT cn.id, cn.headline, cn.published_at, cn.category, cn.nav_impact,
                   cn.processing_status, cn.summary, cn.notes,
                   sd.url, sd.external_id, sd.metadata_json, s.code AS source_code
            FROM company_news cn
            JOIN instruments i ON i.id = cn.issuer_instrument_id
            JOIN source_documents sd ON sd.id = cn.source_document_id
            JOIN sources s ON s.id = sd.source_id
            WHERE i.symbol = 'BMOB3'{category_sql}
            ORDER BY cn.published_at DESC, cn.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        if not include_superseded and metadata.get("is_latest_version") is False:
            continue
        items.append(
            {
                "id": row["id"],
                "headline": row["headline"],
                "published_at": row["published_at"],
                "category": row["category"],
                "nav_impact": row["nav_impact"],
                "processing_status": row["processing_status"],
                "summary": row["summary"],
                "url": row["url"],
                "source": row["source_code"],
                "external_id": row["external_id"],
                "reference_date": metadata.get("reference_date"),
                "cvm_category": metadata.get("cvm_category"),
                "cvm_type": metadata.get("cvm_type"),
                "cvm_species": metadata.get("cvm_species"),
                "cvm_subject": metadata.get("cvm_subject"),
                "version": metadata.get("version"),
                "is_latest_version": metadata.get("is_latest_version", True),
            }
        )
        if len(items) >= safe_limit:
            break
    return {"count": len(items), "items": items}

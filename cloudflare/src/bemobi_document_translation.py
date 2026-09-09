from __future__ import annotations

import hashlib
import io
import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from pypdf import PdfReader

from bounded_response import read_response_bytes

MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_CHUNK_CHARACTERS = 12_000
TRANSLATOR_VERSION = "bemobi-nb-v1"
DEFAULT_WORKERS_AI_MODEL = "@cf/meta/llama-3.1-8b-instruct"
_SAFE_KEY = re.compile(r"^translated/bemobi/[0-9a-f]{64}/bemobi-norsk\.pdf$")
_VALUE_RE = re.compile(
    r"(?:R\$|BRL)\s*[\d.,]+|\d+(?:[.,]\d+)?\s*%|"
    r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d[\d.,]*\b",
    re.IGNORECASE,
)
_RETRYABLE_EXTERNAL_ERROR_RE = re.compile(
    r"(?:rate[ -]?limit|HTTP (?:408|429|5\d\d)\b)", re.IGNORECASE
)


class TranslationProvider(Protocol):
    model: str

    async def complete(self, instruction: str, text: str) -> str: ...


@dataclass(frozen=True)
class WorkersAIProvider:
    """Adapter for den native Workers AI-bindingen i Cloudflare-runtime."""

    ai: Any
    model: str

    async def complete(self, instruction: str, text: str) -> str:
        result = self.ai.run(
            self.model,
            {
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": text},
                ],
                "temperature": 0,
                "max_tokens": 4096,
            },
        )
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict):
            response = result.get("response")
        else:
            response = getattr(result, "response", None)
            to_py = getattr(response, "to_py", None)
            if callable(to_py):
                response = to_py()
        text_response = str(response or "").strip()
        if not text_response:
            raise RuntimeError("Workers AI returnerte et tomt eller ugyldig svar")
        return text_response


def detect_language(text: str) -> str:
    """Deterministisk innholdsbasert språkvalg for portugisisk, engelsk og norsk."""
    words = re.findall(r"[a-zà-ÿ]+", text.casefold())
    markers = {
        "pt": {"de", "da", "do", "dos", "para", "ações", "companhia", "administração"},
        "en": {"the", "and", "of", "for", "shares", "company", "board"},
        "nb": {"og", "av", "for", "aksjer", "selskapet", "styret", "ikke"},
    }
    scores = {
        language: sum(word in terms for word in words)
        for language, terms in markers.items()
    }
    language, score = max(scores.items(), key=lambda item: item[1])
    return language if score >= 2 else "unknown"


def extract_pdf_text(payload: bytes) -> str:
    reader = PdfReader(io.BytesIO(payload))
    pages = [str(page.extract_text() or "").strip() for page in reader.pages]
    return "\n\n".join(page for page in pages if page).strip()


def stable_chunks(
    text: str, limit: int = MAX_CHUNK_CHARACTERS
) -> list[tuple[str, str]]:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        parts = [
            paragraph[index : index + limit]
            for index in range(0, len(paragraph), limit)
        ]
        for part in parts:
            candidate = f"{current}\n\n{part}".strip()
            if current and len(candidate) > limit:
                chunks.append(current)
                current = part
            else:
                current = candidate
    if current:
        chunks.append(current)
    return [(f"chunk-{index:04d}", chunk) for index, chunk in enumerate(chunks, 1)]


def validate_preserved_values(original: str, translated: str) -> list[str]:
    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value).casefold()

    source = {normalize(value) for value in _VALUE_RE.findall(original)}
    target = {normalize(value) for value in _VALUE_RE.findall(translated)}
    return sorted(source - target)


def translated_object_key(content_hash: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
        raise ValueError("Ugyldig innholdshash")
    return f"translated/bemobi/{content_hash}/bemobi-norsk.pdf"


def is_safe_translated_key(key: str) -> bool:
    return _SAFE_KEY.fullmatch(key) is not None


def _is_retryable_external_error(error: Exception) -> bool:
    return isinstance(error, (ConnectionError, TimeoutError)) or (
        isinstance(error, RuntimeError)
        and _RETRYABLE_EXTERNAL_ERROR_RE.search(str(error)) is not None
    )


def _pdf_escape(text: str) -> bytes:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("cp1252", errors="replace")
    )


def render_norwegian_pdf(title: str, published_at: str, body: str) -> bytes:
    """Lag en enkel PDF 1.4 uten ny runtime-avhengighet."""
    header = [
        "Bemobi Mobile Tech S.A.",
        title,
        published_at[:10],
        "",
        "UOFFISIELL NORSK OVERSETTELSE",
        "Denne oversettelsen er generert automatisk for å gjøre dokumentet lettere",
        "tilgjengelig. Det portugisiske originaldokumentet fra Bemobi/CVM er den",
        "autoritative kilden.",
        "",
    ]
    lines = header[:]
    for paragraph in body.splitlines():
        words = paragraph.split()
        line = ""
        for word in words:
            if len(line) + len(word) + 1 > 92:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
    pages = [lines[index : index + 48] for index in range(0, len(lines), 48)] or [[]]
    objects: list[bytes] = []
    page_ids = [4 + index * 2 for index in range(len(pages))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = b" ".join(f"{page_id} 0 R".encode() for page_id in page_ids)
    objects.append(
        b"<< /Type /Pages /Kids ["
        + kids
        + b"] /Count "
        + str(len(pages)).encode()
        + b" >>"
    )
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    for page_id, page_lines in zip(page_ids, pages, strict=True):
        content_id = page_id + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        commands = [b"BT /F1 10 Tf 50 790 Td 13 TL"]
        commands.extend(b"(" + _pdf_escape(line) + b") Tj T*" for line in page_lines)
        commands.append(b"ET")
        stream = b"\n".join(commands)
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    result.extend(
        b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    )
    result.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(result)


_TRANSLATE_INSTRUCTION = """Oversett hele portugisiske dokumentdelen til norsk bokmål. Bevar overskrifter, avsnitt, nummerering og tabellstruktur. Ikke endre, utelat eller tolke tall, valuta, prosenter, datoer, selskapsnavn, personnavn eller registreringsnumre. Bruk konsekvent: juros sobre capital próprio = renter på egenkapital (JCP), programa de recompra de ações = tilbakekjøpsprogram for aksjer, fato relevante = vesentlig melding, assembleia geral = generalforsamling, conselho de administração = styret. Returner bare oversettelsen."""
_SUMMARY_INSTRUCTION = """Skriv på norsk bokmål en faktabasert investorsammendrag på 2–5 korte setninger, innledet med «Kort fortalt:». Ta bare med hendelser, beløp, datoer og Otello-effekt som dokumentet gir dekning for. Skill tydelig mellom fakta, beregning og tolkning. Ikke klassifiser vesentlighet og ikke finn på tall. Returner JSON med strengfeltene title og summary."""


async def process_pending_translations(
    repository: Any,
    bucket: Any,
    provider: TranslationProvider,
    *,
    limit: int = 3,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    rows = await repository.all(
        """SELECT sd.id, sd.url, sd.title, sd.published_at, sd.content_sha256
           FROM source_documents sd JOIN sources s ON s.id=sd.source_id
           WHERE s.code IN ('CVM','BEMOBI_IR') AND sd.translation_status='PENDING'
           ORDER BY sd.id LIMIT ?""",
        (max(1, min(limit, 20)),),
    )
    completed = failed = 0
    for row in rows:
        document_id = int(row["id"])
        claimed = await repository.run(
            "UPDATE source_documents SET translation_status='PROCESSING' WHERE id=? AND translation_status='PENDING'",
            (document_id,),
        )
        if (
            getattr(claimed, "meta", None) is not None
            and int(claimed.meta.changes) == 0
        ):
            continue
        print(f"bemobi_translation processing document_id={document_id}")
        try:
            downloader = fetcher
            if downloader is None:
                from workers import fetch

                downloader = fetch
            response = await downloader(
                str(row["url"]), headers={"Accept": "application/pdf"}
            )
            if not bool(getattr(response, "ok", False)):
                raise RuntimeError(
                    f"originaldokument HTTP {getattr(response, 'status', 'ukjent')}"
                )
            payload = await read_response_bytes(
                response, max_bytes=MAX_PDF_BYTES, label="Bemobi PDF"
            )
            content_hash = hashlib.sha256(payload).hexdigest()
            duplicate = await repository.first(
                """SELECT original_language, extraction_status, summary_status,
                          norwegian_title, norwegian_summary, translated_pdf_key,
                          translator_model, translator_version, translation_character_count
                   FROM source_documents
                   WHERE content_sha256=? AND translation_status='READY' AND id<>?
                   LIMIT 1""",
                (content_hash, document_id),
            )
            if duplicate:
                await repository.run(
                    """UPDATE source_documents SET content_sha256=?, original_language=?,
                       extraction_status=?, translation_status='READY', summary_status=?,
                       norwegian_title=?, norwegian_summary=?, translated_pdf_key=?,
                       translator_model=?, translator_version=?, translation_character_count=?,
                       translation_error=NULL,
                       translation_processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                    (
                        content_hash,
                        duplicate.get("original_language"),
                        duplicate.get("extraction_status"),
                        duplicate.get("summary_status"),
                        duplicate.get("norwegian_title"),
                        duplicate.get("norwegian_summary"),
                        duplicate.get("translated_pdf_key"),
                        duplicate.get("translator_model"),
                        duplicate.get("translator_version"),
                        duplicate.get("translation_character_count"),
                        document_id,
                    ),
                )
                print(f"bemobi_translation ready document_id={document_id} reused=true")
                completed += 1
                continue
            text = extract_pdf_text(payload)
            if len(re.sub(r"\s+", "", text)) < 80:
                raise ValueError("PDF-en mangler lesbar tekst og krever OCR")
            language = detect_language(text)
            if language != "pt":
                await repository.run(
                    """UPDATE source_documents SET original_language=?, extraction_status='READY',
                       translation_status='NOT_REQUIRED', summary_status='NOT_REQUIRED',
                       translation_processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                    (language, document_id),
                )
                completed += 1
                continue
            translations = []
            for chunk_id, chunk in stable_chunks(text):
                translated = await provider.complete(
                    _TRANSLATE_INSTRUCTION, f"[{chunk_id}]\n{chunk}"
                )
                translations.append(translated)
            full_translation = "\n\n".join(translations)
            missing = validate_preserved_values(text, full_translation)
            if missing:
                raise ValueError(f"verdikontroll feilet ({len(missing)} mangler)")
            summary_raw = await provider.complete(_SUMMARY_INSTRUCTION, text)
            summary = json.loads(summary_raw)
            title = str(summary["title"]).strip()
            norwegian_summary = str(summary["summary"]).strip()
            key = translated_object_key(content_hash)
            pdf = render_norwegian_pdf(
                title, str(row.get("published_at") or ""), full_translation
            )
            await bucket.put(key, pdf, http_metadata={"contentType": "application/pdf"})
            await repository.run(
                """UPDATE source_documents SET content_sha256=?, original_language='pt',
                   extraction_status='READY', translation_status='READY', summary_status='READY',
                   norwegian_title=?, norwegian_summary=?, translated_pdf_key=?, translation_error=NULL,
                   translation_processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                   translator_model=?, translator_version=?, translation_character_count=? WHERE id=?""",
                (
                    content_hash,
                    title,
                    norwegian_summary,
                    key,
                    provider.model,
                    TRANSLATOR_VERSION,
                    len(text),
                    document_id,
                ),
            )
            print(f"bemobi_translation ready document_id={document_id}")
            completed += 1
        except Exception as exc:
            reason = str(exc)[:300]
            if _is_retryable_external_error(exc):
                await repository.run(
                    """UPDATE source_documents SET extraction_status=COALESCE(extraction_status,'PENDING'),
                       translation_status='PENDING', summary_status='PENDING', translation_error=?,
                       translation_processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                    (reason, document_id),
                )
            else:
                await repository.run(
                    """UPDATE source_documents SET extraction_status=COALESCE(extraction_status,'FAILED'),
                       translation_status='FAILED', summary_status='FAILED', translation_error=?,
                       translation_processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                    (reason, document_id),
                )
            print(
                f"bemobi_translation failed document_id={document_id} reason={reason}"
            )
            failed += 1
    return {"selected": len(rows), "completed": completed, "failed": failed}


async def queue_translation_backfill(
    repository: Any,
    *,
    document_id: int | None = None,
    after: str | None = None,
    limit: int = 10,
) -> int:
    conditions = [
        "s.code IN ('CVM','BEMOBI_IR')",
        "COALESCE(sd.translation_status,'') NOT IN ('READY','PROCESSING')",
    ]
    parameters: list[Any] = []
    if document_id is not None:
        conditions.append("sd.id=?")
        parameters.append(document_id)
    if after is not None:
        conditions.append("substr(sd.published_at,1,10)>=?")
        parameters.append(after)
    parameters.append(max(1, min(limit, 100)))
    rows = await repository.all(
        f"SELECT sd.id FROM source_documents sd JOIN sources s ON s.id=sd.source_id WHERE {' AND '.join(conditions)} ORDER BY sd.id DESC LIMIT ?",
        tuple(parameters),
    )
    for row in rows:
        await repository.run(
            "UPDATE source_documents SET translation_status='PENDING', translation_error=NULL WHERE id=?",
            (int(row["id"]),),
        )
        print(f"bemobi_translation queued document_id={int(row['id'])}")
    return len(rows)

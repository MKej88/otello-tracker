from __future__ import annotations

import asyncio
import hashlib
import io
import inspect
import json
import re
from urllib.parse import urlencode, urlsplit
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Protocol

from pypdf import PdfReader

from bounded_response import read_response_bytes

MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_CHUNK_CHARACTERS = 4_000
MAX_SUMMARY_CHARACTERS = 48_000
MAX_DOCUMENT_CHUNKS = 40
MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024
MAX_SUMMARY_RESPONSE_CHARS = 16_384
TRANSLATOR_VERSION = "bemobi-nb-v2"
DEFAULT_WORKERS_AI_MODEL = "@cf/google/gemma-4-26b-a4b-it"
STALE_PROCESSING_HOURS = 6
MAX_TRANSLATION_ATTEMPTS = 3
RETRY_DELAY_HOURS = 6

# Both nightly and half-hour workers use the same atomic claim predicate.
_ELIGIBLE = """(
    (translation_status='PENDING' AND translation_attempts < 3
        AND (translation_attempts=0 OR translation_processed_at IS NULL
             OR translation_processed_at < strftime('%Y-%m-%dT%H:%M:%fZ','now','-6 hours')))
    OR (translation_status='FAILED' AND translation_attempts < 3
        AND (translation_processed_at IS NULL OR translation_processed_at < strftime('%Y-%m-%dT%H:%M:%fZ','now','-6 hours')))
    OR (translation_status='PROCESSING'
        AND (translation_processed_at IS NULL OR translation_processed_at < strftime('%Y-%m-%dT%H:%M:%fZ','now','-6 hours')))
)"""
_SAFE_KEY = re.compile(r"^translated/bemobi/[0-9a-f]{64}/bemobi-norsk\.pdf$")
_VALUE_RE = re.compile(
    r"(?:R\$|BRL)\s*[\d.,]+|\d+(?:[.,]\d+)?\s*%|"
    r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d[\d.,]*\b",
    re.IGNORECASE,
)
_RETRYABLE_EXTERNAL_ERROR_RE = re.compile(
    r"(?:rate[ -]?limit|out of capacity|HTTP (?:408|429|5\d\d)\b)", re.IGNORECASE
)


# Only fixed, documented provider codes and categories are emitted in diagnostics.
AI_ERROR_CODES = frozenset({3003, 3006, 3007, 3008, 3023, 3036, 3039, 3040, 3041, 3042,
                            5004, 5005, 5007, 5016, 5018, 5019, 5028, 5035})
_AI_CODE_CATEGORY = {
    3003: "invalid_request", 3006: "request_too_large", 3007: "timeout", 3008: "timeout",
    3023: "account_access", 3036: "quota", 3040: "capacity", 3041: "account_access",
    3042: "model_unavailable", 5007: "model_unavailable", 5016: "account_access",
    5018: "account_access", 5019: "invalid_request", 5028: "model_unavailable", 5035: "account_access",
    3039: "invalid_request", 5004: "invalid_request", 5005: "invalid_request",
}


class WorkersAIError(RuntimeError):
    def __init__(self, category: str, *, code: int | None = None, http: int | None = None,
                 detail: str = "Workers AI-kall feilet"):
        self.category = category
        self.code = code
        self.http = http
        super().__init__(detail)


def _classify_ai_exception(exc: Exception) -> WorkersAIError:
    # Never print the provider message, which may contain document text or credentials.
    message = str(exc)
    code = getattr(exc, "code", None)
    if type(code) is not int or code not in AI_ERROR_CODES:
        # Cloudflare's error strings may prefix a numeric internal code.
        match = re.search(r"(?i)(?:inferenceerror|aigatewayerror|aierror|error(?: code)?|code)\s*[:=]?\s*(\d{4})\b", message)
        code = int(match[1]) if match and int(match[1]) in AI_ERROR_CODES else None
    http = getattr(exc, "status", None)
    if type(http) is not int or not 400 <= http <= 599:
        match = re.search(r"(?i)\bHTTP\s+([45]\d\d)\b", message)
        http = int(match[1]) if match else None
    lower = message.lower()
    category = _AI_CODE_CATEGORY.get(code)
    if category is None:
        if isinstance(exc, TimeoutError) or http == 408 or "timeout" in lower:
            category = "timeout"
        elif "rate limit" in lower or "rate-limit" in lower or "quota" in lower or "neurons" in lower:
            category = "quota"
        elif "capacity" in lower or http == 429:
            category = "capacity"
        elif http in (401, 403):
            category = "account_access"
        elif http in (404, 410) or "no such model" in lower or "model deprecated" in lower:
            category = "model_unavailable"
        elif http == 413:
            category = "request_too_large"
        elif http == 400:
            category = "invalid_request"
        elif http is not None and http >= 500:
            category = "provider_error"
        else:
            category = "binding_error"
    return WorkersAIError(category, code=code, http=http,
                          detail="rate limit" if category == "quota" else "Workers AI-kall feilet")


def _ai_error_info(exc: Exception) -> dict[str, Any]:
    error = exc if isinstance(exc, WorkersAIError) else _classify_ai_exception(exc)
    return {"category": error.category, "code": error.code, "http": error.http}


class TranslationProvider(Protocol):
    model: str

    async def complete(self, instruction: str, text: str) -> str: ...


@dataclass(frozen=True)
class WorkersAIProvider:
    """Adapter for den native Workers AI-bindingen i Cloudflare-runtime."""

    ai: Any
    model: str
    trace: dict[str, Any] | None = None
    max_output_tokens: int = 4096

    async def complete(self, instruction: str, text: str) -> str:
        inputs = {
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
        }
        if self.model == DEFAULT_WORKERS_AI_MODEL:
            inputs.pop("max_tokens")
            inputs["max_completion_tokens"] = self.max_output_tokens
            inputs["chat_template_kwargs"] = {"enable_thinking": False}
        # Native bindings expect a JavaScript object, not a Python dict proxy/Map.
        try:
            from js import Object
            from pyodide.ffi import to_js
        except ImportError:
            payload = inputs  # CPython tests
        else:
            payload = to_js(inputs, dict_converter=Object.fromEntries)
        if self.trace is not None:
            self.trace["ai_binding_calls"] += 1
        try:
            result = self.ai.run(self.model, payload)
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=90)
        except Exception as exc:
            raise _classify_ai_exception(exc) from exc
        if not isinstance(result, dict):
            # JSON round-trip converts nested JS arrays/objects reliably.
            try:
                from js import JSON
                result = json.loads(str(JSON.stringify(result)))
            except ImportError:
                converter = getattr(result, "to_py", None)
                if callable(converter):
                    result = converter()
        if not isinstance(result, dict):
            raise WorkersAIError("invalid_response", detail="Workers AI returnerte et ugyldig svarformat")
        response = result.get("response")
        if isinstance(result.get("choices"), list) and result["choices"]:
            choice = result["choices"][0]
            if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
                finish = choice.get("finish_reason") if isinstance(choice, dict) else None
                raise WorkersAIError("truncated" if finish == "length" else "invalid_response",
                                     detail="Workers AI fullførte ikke tekstgenereringen")
            message = choice.get("message")
            response = message.get("content") if isinstance(message, dict) else None
        if not isinstance(response, str) or not response.strip():
            raise WorkersAIError("empty_response", detail="Workers AI returnerte et tomt eller ugyldig svar")
        return response.strip()



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


class ValuePreservationError(ValueError):
    def __init__(self, missing_count: int):
        self.missing_count = missing_count
        super().__init__(f"verdikontroll feilet ({missing_count} mangler)")


async def translate_verified_chunk(provider, chunk_id: str, chunk: str, trace: dict) -> str:
    # Keep the exact existing value-preservation policy. Retry the entire
    # affected chunk, not just the missing numbers, to preserve their context.
    # Do not include a numbered artificial chunk identifier in the AI input.
    translated = await provider.complete(_TRANSLATE_INSTRUCTION, chunk)
    missing = validate_preserved_values(chunk, translated)
    if missing:
        trace["value_chunk_retries"] = trace.get("value_chunk_retries", 0) + 1
        translated = await provider.complete(
            _TRANSLATE_INSTRUCTION + "\nForrige svar manglet tall eller datoer. "
            "Kontroller hele originalen linje for linje. Behold tall, skilletegn, "
            "valutamerker, prosenttegn og datoer nøyaktig som i originalen. "
            "Ikke legg til en liste med manglende verdier; oversett alt i riktig sammenheng.",
            chunk,
        )
        missing = validate_preserved_values(chunk, translated)
    if missing:
        trace["value_missing_count"] = len(missing)
        trace["value_failed_chunk"] = chunk_id
        raise ValuePreservationError(len(missing))
    return translated


def translated_object_key(content_hash: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
        raise ValueError("Ugyldig innholdshash")
    return f"translated/bemobi/{content_hash}/bemobi-norsk.pdf"


def is_safe_translated_key(key: str) -> bool:
    return _SAFE_KEY.fullmatch(key) is not None


def _is_retryable_external_error(error: Exception) -> bool:
    if isinstance(error, WorkersAIError):
        return error.category in {"quota", "capacity", "timeout", "provider_error", "binding_error"}
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
_SUMMARY_INSTRUCTION = """Skriv på norsk bokmål en faktabasert investorsammendrag på 2–5 korte setninger, innledet med «Kort fortalt:». Ta bare med hendelser, beløp, datoer og Otello-effekt som dokumentet gir dekning for. Skill tydelig mellom fakta, beregning og tolkning. Ikke klassifiser vesentlighet og ikke finn på tall. Returner nøyaktig ett JSON-objekt med strengfeltene title og summary. Ingen Markdown, kodegjerder eller forklaring utenfor objektet. Escape anførselstegn og linjeskift som gyldig JSON."""


class SummaryFormatError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _unique_json_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SummaryFormatError("duplicate_field", "Workers AI-oppsummeringen har duplikate JSON-felt")
        result[key] = value
    return result


def parse_summary_response(payload: str) -> tuple[str, str]:
    if not isinstance(payload, str) or len(payload) > MAX_SUMMARY_RESPONSE_CHARS:
        raise SummaryFormatError("size_or_type", "Workers AI-oppsummeringen har ugyldig størrelse eller type")
    payload = payload.strip().lstrip("\ufeff").strip()
    # Accept one complete JSON code fence, never search arbitrary prose for a JSON fragment.
    fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", payload, re.DOTALL | re.IGNORECASE)
    if fenced:
        payload = fenced.group(1).strip()
    try:
        summary = json.loads(payload, object_pairs_hook=_unique_json_fields)
    except json.JSONDecodeError as exc:
        raise SummaryFormatError("invalid_json", "Workers AI-oppsummeringen er ikke gyldig JSON") from exc
    if not isinstance(summary, dict):
        raise SummaryFormatError("not_object", "Workers AI-oppsummeringen er ikke et JSON-objekt")

    title = summary.get("title")
    norwegian_summary = summary.get("summary")
    if not isinstance(title, str) or not title.strip():
        raise SummaryFormatError("invalid_title", "Workers AI-oppsummeringen mangler et gyldig title-felt")
    if not isinstance(norwegian_summary, str) or not norwegian_summary.strip():
        raise SummaryFormatError("invalid_summary", "Workers AI-oppsummeringen mangler et gyldig summary-felt")
    if set(summary) != {"title", "summary"}:
        raise SummaryFormatError("unexpected_fields", "Workers AI-oppsummeringen har uventede JSON-felt")
    if len(title) > 500 or len(norwegian_summary) > 5000:
        raise SummaryFormatError("size_or_type", "Workers AI-oppsummeringen overskrider lengdegrensen")
    return title.strip(), norwegian_summary.strip()


def _checkpoint_identity(content_hash: str, text: str, model: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
        raise ValueError("Ugyldig innholdshash")
    return {"pdf_sha256": content_hash, "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "model": model, "version": TRANSLATOR_VERSION}


def _checkpoint_key(identity: dict[str, str]) -> str:
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    # Deliberately outside the public translated-PDF allowlist.
    return f"private/bemobi/translation-checkpoints/v1/{identity['pdf_sha256']}/{digest}.json"


async def _read_translation_checkpoint(bucket, identity, original: str) -> str | None:
    from bemobi_cvm_mirror import _read

    try:
        raw = await _read(bucket, _checkpoint_key(identity), MAX_CHECKPOINT_BYTES)
        checkpoint = json.loads(raw)
        translated = checkpoint["translation"]
        if (checkpoint["identity"] != identity or not isinstance(translated, str)
                or not translated.strip()
                or hashlib.sha256(translated.encode()).hexdigest() != checkpoint["translation_sha256"]
                or validate_preserved_values(original, translated)):
            return None
        return translated
    except Exception:
        return None


async def _write_translation_checkpoint(bucket, identity, translated: str) -> None:
    checkpoint = {"identity": identity, "translation": translated,
                  "translation_sha256": hashlib.sha256(translated.encode()).hexdigest()}
    raw = json.dumps(checkpoint, ensure_ascii=False).encode()
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Mellomlagret oversettelse er for stor")
    await bucket.put(_checkpoint_key(identity), raw, http_metadata={"contentType": "application/json"})


def _official_document_fallbacks(url: str) -> list[str]:
    """Transport alternatives only; never substitute a different filing."""
    from bemobi_cvm_rad import CANONICAL, DOWNLOAD, filing_identity
    from bemobi_web_refresh import _official_mziq_document_fallbacks

    identity = filing_identity(url)
    if identity:
        protocol, sequence, version = identity
        canonical = CANONICAL if urlsplit(url).path != urlsplit(CANONICAL).path else DOWNLOAD
        return [canonical + "?" + urlencode({
            "CodigoInstituicao": 1, "Tela": "99" if canonical == CANONICAL else "ext",
            "descTipo": "IPE", "numProtocolo": protocol, "numSequencia": sequence,
            "numVersao": version,
        })]
    return _official_mziq_document_fallbacks(url)


async def _download_original(url: str, bucket: Any, downloader: Any,
                             *, trace: dict[str, Any] | None = None,
                             delivery: str | None = None, document_id: int | None = None) -> bytes:
    from bemobi_cvm_rad import filing_identity
    from bemobi_verified_mirror import PINNED_Q3_DOCUMENTS, read_verified_q3_document

    if document_id == 7540 and bucket is not None:
        from bemobi_7540_normalization import read_7540_normalization
        attempt = {"route": "normalized_r2", "result": "error"}
        if trace is not None:
            trace["downloads"].append(attempt)
        # This incident must use only the independently verified processing copy.
        # Do not silently fall back to the rejected padded transport body.
        payload = await read_7540_normalization(bucket, url, delivery=delivery, document_id=document_id)
        attempt["result"] = "ok"
        return payload

    original_error = None
    for index, candidate in enumerate([url, *_official_document_fallbacks(url)]):
        attempt = {"route": "original" if index == 0 else "official_alternative", "result": "error"}
        if trace is not None:
            trace["downloads"].append(attempt)
        try:
            response = await downloader(candidate, headers={"Accept": "application/pdf"})
            status = getattr(response, "status", None)
            if type(status) is int and 100 <= status <= 599:
                attempt["http"] = status
            if not bool(getattr(response, "ok", False)):
                attempt["result"] = "http_error"
                raise RuntimeError(f"originaldokument HTTP {getattr(response, 'status', 'ukjent')}")
            payload = await read_response_bytes(response, max_bytes=MAX_PDF_BYTES, label="Bemobi PDF")
            if not payload.startswith(b"%PDF"):
                attempt["result"] = "not_pdf"
                raise ValueError("Originaldokumentet er ikke en PDF")
            if filing_identity(url) and b"%%EOF" not in payload[-2048:]:
                raise ValueError("CVM-PDF krever verifisert behandlingskopi")
            attempt["result"] = "ok"
            return payload
        except Exception as exc:
            if original_error is None:
                original_error = exc
    # Existing private R2 copies are pinned to exact official CVM filing IDs and hashes.
    identity = filing_identity(url)
    if identity and bucket is not None:
        for kind, document in PINNED_Q3_DOCUMENTS.items():
            if identity == filing_identity(document["url"]):
                attempt = {"route": "verified_r2", "result": "error"}
                if trace is not None:
                    trace["downloads"].append(attempt)
                try:
                    payload, _ = await read_verified_q3_document(bucket, kind)
                    attempt["result"] = "ok"
                    return payload
                except Exception:
                    pass
        from bemobi_translation_mirror import read_translation_mirror
        attempt = {"route": "queue_r2", "result": "error"}
        if trace is not None:
            trace["downloads"].append(attempt)
        try:
            payload = await read_translation_mirror(bucket, url, delivery=delivery)
            attempt["result"] = "ok"
            return payload
        except Exception:
            pass
    raise original_error


async def _summary_once_with_retry(provider: TranslationProvider, text: str) -> tuple[str, str]:
    # Retry format errors once, using the original text rather than an invalid response.
    try:
        return parse_summary_response(await provider.complete(_SUMMARY_INSTRUCTION, text))
    except SummaryFormatError:
        return parse_summary_response(await provider.complete(
            _SUMMARY_INSTRUCTION + '\nForrige svar kunne ikke valideres. Svar kun med gyldig JSON: '
            '{"title":"Norsk tittel","summary":"Kort fortalt: Norsk sammendrag."}', text))


async def _summarize_document(provider: TranslationProvider, text: str) -> tuple[str, str]:
    if len(text) <= MAX_SUMMARY_CHARACTERS:
        return await _summary_once_with_retry(provider, text)
    # Summarize all sections, never silently truncate a long financial filing.
    summaries = []
    for _, chunk in stable_chunks(text, limit=MAX_SUMMARY_CHARACTERS):
        title, summary = await _summary_once_with_retry(provider, chunk)
        summaries.append(title + "\n" + summary)
    combined = "\n\n".join(summaries)
    if len(combined) > MAX_SUMMARY_CHARACTERS:
        raise ValueError("Deloppsummeringene overskrider sikker lengdegrense")
    return await _summary_once_with_retry(provider, combined)


@dataclass
class _ObservedProvider:
    provider: TranslationProvider
    trace: dict[str, Any]

    @property
    def model(self) -> str:
        return self.provider.model

    async def complete(self, instruction: str, text: str) -> str:
        self.trace["ai_provider_calls"] += 1
        response = await self.provider.complete(instruction, text)
        self.trace["ai_responses"] += 1
        return response


def _new_trace(document_id: int, source: Any, provider: TranslationProvider) -> dict[str, Any]:
    return {
        "document_id": document_id, "source": source if source in ("CVM", "BEMOBI_IR") else "unknown",
        "stage": "claim", "outcome": "error", "downloads": [],
        "ai_provider_calls": 0, "ai_binding_calls": 0, "ai_responses": 0,
        "native_binding": isinstance(provider, WorkersAIProvider),
    }


async def process_pending_translations(
    repository: Any,
    bucket: Any,
    provider: TranslationProvider,
    *,
    limit: int = 3,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = await repository.all(
        f"""SELECT sd.id, sd.url, sd.title, sd.published_at, sd.content_sha256,
                  sd.translation_attempts, s.code AS source_code
           FROM source_documents sd JOIN sources s ON s.id=sd.source_id
           WHERE s.code IN ('CVM','BEMOBI_IR') AND {_ELIGIBLE}
           ORDER BY sd.published_at DESC, sd.id DESC LIMIT ?""",
        (max(1, min(limit, 20)),),
    )
    completed = failed = 0
    for row in rows:
        document_id = int(row["id"])
        claimed = await repository.run(
            f"""UPDATE source_documents
               SET translation_status='PROCESSING',
                   translation_attempts=translation_attempts+1,
                   translation_processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE id=? AND {_ELIGIBLE}""",
            (document_id,),
        )
        if (
            getattr(claimed, "meta", None) is not None
            and int(claimed.meta.changes) == 0
        ):
            continue
        print(f"bemobi_translation processing document_id={document_id}")
        attempts_before = int(row.get("translation_attempts") or 0)
        trace = _new_trace(document_id, row.get("source_code"), provider)
        if diagnostics is not None:
            diagnostics.append(trace)
        underlying = replace(provider, trace=trace) if isinstance(provider, WorkersAIProvider) else provider
        observed = _ObservedProvider(underlying, trace)
        stage = "claim"
        try:
            if attempts_before >= MAX_TRANSLATION_ATTEMPTS:
                raise ValueError("Maksimalt antall behandlingsforsøk etter avbrutt kjøring")
            downloader = fetcher
            if downloader is None:
                from workers import fetch

                downloader = fetch
            stage = "download"
            payload = await _download_original(str(row["url"]), bucket, downloader, trace=trace,
                                               delivery=str(row.get("published_at") or "") or None,
                                               document_id=document_id)
            stage = "deduplication"
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
                trace.update(stage="deduplication", outcome="reused")
                print(f"bemobi_translation ready document_id={document_id} reused=true")
                completed += 1
                continue
            stage = "pdf_extraction"
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
                trace.update(stage="pdf_extraction", outcome="not_required")
                completed += 1
                continue
            stage = "translation"
            chunks = stable_chunks(text)
            trace["source_characters"] = len(text)
            trace["source_chunks"] = len(chunks)
            if len(chunks) > MAX_DOCUMENT_CHUNKS:
                trace["translation_limit"] = "max_document_chunks"
                raise ValueError("Dokumentet overskrider sikker behandlingsgrense")
            identity = _checkpoint_identity(content_hash, text, provider.model)
            full_translation = await _read_translation_checkpoint(bucket, identity, text)
            trace["translation_checkpoint"] = "reused" if full_translation is not None else "miss"
            if full_translation is None:
                translations = []
                for chunk_id, chunk in chunks:
                    stage = "value_validation"
                    translated = await translate_verified_chunk(observed, chunk_id, chunk, trace)
                    stage = "translation"
                    translations.append(translated)
                full_translation = "\n\n".join(translations)
            stage = "value_validation"
            missing = validate_preserved_values(text, full_translation)
            if missing:
                trace["value_missing_count"] = len(missing)
                raise ValuePreservationError(len(missing))
            if trace["translation_checkpoint"] != "reused":
                try:
                    await _write_translation_checkpoint(bucket, identity, full_translation)
                    trace["translation_checkpoint"] = "saved"
                except Exception:
                    # Storage failure must not prevent normal successful publication.
                    trace["translation_checkpoint"] = "write_failed"
            stage = "summary"
            title, norwegian_summary = await _summarize_document(observed, text)
            stage = "archive"
            key = translated_object_key(content_hash)
            pdf = render_norwegian_pdf(
                title, str(row.get("published_at") or ""), full_translation
            )
            await bucket.put(key, pdf, http_metadata={"contentType": "application/pdf"})
            stage = "database_write"
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
            trace.update(stage="database_write", outcome="ready")
            print(f"bemobi_translation ready document_id={document_id}")
            completed += 1
        except Exception as exc:
            # Store stage and exception class; raw diagnostic stays private in D1.
            trace.update(stage=stage, outcome="error")
            if isinstance(exc, WorkersAIError):
                if stage == "value_validation":
                    stage = "translation"
                    trace["stage"] = stage
                trace["ai_error"] = _ai_error_info(exc)
                # A stable, redacted marker makes the error queryable without raw provider messages.
                reason = f"{stage}:WorkersAIError: ai_category={exc.category}; ai_code={exc.code or 0}; ai_http={exc.http or 0}"
            elif isinstance(exc, SummaryFormatError):
                trace["summary_error"] = exc.code
                reason = f"{stage}:SummaryFormatError: summary_code={exc.code}"
            else:
                reason = f"{stage}:{type(exc).__name__}: {str(exc)[:240]}"
            if ((_is_retryable_external_error(exc) or isinstance(exc, SummaryFormatError))
                    and attempts_before + 1 < MAX_TRANSLATION_ATTEMPTS):
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
                f"bemobi_translation failed document_id={document_id} stage={stage} type={type(exc).__name__}"
            )
            failed += 1
            if isinstance(exc, WorkersAIError) and exc.category in {
                "quota", "capacity", "timeout", "provider_error", "binding_error",
                "account_access", "model_unavailable", "invalid_request",
            }:
                # A provider-wide failure must not consume the rest of the batch.
                break
    return {"selected": len(rows), "completed": completed, "failed": failed}


async def translation_queue_health(repository: Any) -> dict[str, Any]:
    """Count unresolved documents; do not expose document text or URLs."""
    row = await repository.first(
        """SELECT
           SUM(CASE WHEN translation_status='PENDING' THEN 1 ELSE 0 END) AS pending,
           SUM(CASE WHEN translation_status='PROCESSING' THEN 1 ELSE 0 END) AS processing,
           SUM(CASE WHEN translation_status='FAILED' THEN 1 ELSE 0 END) AS failed,
           SUM(CASE WHEN translation_status='FAILED' AND translation_attempts>=3 THEN 1 ELSE 0 END) AS exhausted,
           SUM(CASE WHEN translation_status='PENDING'
                        AND substr(published_at,1,10)<date('now','-1 day')
                    OR translation_status='PROCESSING'
                        AND (translation_processed_at IS NULL OR translation_processed_at<strftime('%Y-%m-%dT%H:%M:%fZ','now','-6 hours'))
                    THEN 1 ELSE 0 END) AS overdue
           FROM source_documents sd JOIN sources s ON s.id=sd.source_id
           WHERE s.code IN ('CVM','BEMOBI_IR')""",
        (),
    ) or {}
    return {key: int(row.get(key) or 0) for key in
            ("pending", "processing", "failed", "exhausted", "overdue")}


async def probe_workers_ai(provider: WorkersAIProvider) -> dict[str, Any]:
    """Synthetic Portuguese text; no financial PDF, DB writes or document claim."""
    trace = {"ai_binding_calls": 0}
    test_provider = replace(provider, trace=trace, max_output_tokens=128)
    try:
        response = await test_provider.complete(
            "Oversett til norsk bokmål. Bevar tallet. Returner kun oversettelsen.",
            "A empresa tem 123 ações.",
        )
        if "123" not in response or "aksj" not in response.casefold():
            raise WorkersAIError("probe_validation", detail="AI-testen ga ikke forventet norsk tekst")
        return {"status": "ok", "binding_calls": trace["ai_binding_calls"]}
    except Exception as exc:
        return {"status": "error", "binding_calls": trace["ai_binding_calls"],
                "error": _ai_error_info(exc)}


async def run_translation_queue(repository: Any, bucket: Any, provider: TranslationProvider | None,
                                *, limit: int = 3) -> dict[str, Any]:
    if provider is None or bucket is None:
        return {"status": "partial", "reason": "AI- eller dokumentlagerbinding mangler",
                "non_critical": True, "queue": await translation_queue_health(repository)}
    probe = None
    if isinstance(provider, WorkersAIProvider):
        # Probe only if a document is due; avoid needless calls to an empty/delayed queue.
        due = await repository.first(
            f"""SELECT sd.id FROM source_documents sd JOIN sources s ON s.id=sd.source_id
                WHERE s.code IN ('CVM','BEMOBI_IR') AND {_ELIGIBLE} LIMIT 1""", ()
        )
        if due:
            probe = await probe_workers_ai(provider)
            if probe["status"] != "ok":
                return {"status": "partial", "non_critical": True, "model": provider.model,
                        "selected": 0, "completed": 0, "failed": 0, "diagnostics": [],
                        "ai_probe": probe, "queue": await translation_queue_health(repository),
                        "reason": "AI-produksjonstest feilet; dokumentforsøk ikke brukt"}
    diagnostics: list[dict[str, Any]] = []
    result = await process_pending_translations(repository, bucket, provider, limit=limit, diagnostics=diagnostics)
    queue = await translation_queue_health(repository)
    warning = bool(queue["failed"] or queue["overdue"] or result["failed"])
    return {
        **result, "status": "partial" if warning else "ok", "non_critical": True,
        "model": provider.model,
        "ai_probe": probe or {"status": "not_run"},
        "diagnostics": diagnostics,
        "queue": queue,
        **({"reason": f"{queue['failed']} feilet ({queue['exhausted']} uten flere automatiske forsøk), "
                      f"{queue['overdue']} forsinket, {result['failed']} feil i denne kjøringen"} if warning else {}),
    }


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
    document_ids = tuple(int(row["id"]) for row in rows)
    if document_ids:
        placeholders = ",".join("?" for _ in document_ids)
        await repository.run(
            f"""UPDATE source_documents
                SET translation_status='PENDING', translation_error=NULL, translation_attempts=0
                WHERE id IN ({placeholders})""",
            document_ids,
        )
    for document_id in document_ids:
        print(f"bemobi_translation queued document_id={document_id}")
    return len(rows)

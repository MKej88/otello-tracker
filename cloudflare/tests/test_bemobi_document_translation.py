from __future__ import annotations

import io
import hashlib
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from bemobi_document_translation import (  # noqa: E402
    DEFAULT_WORKERS_AI_MODEL,
    WorkersAIProvider,
    probe_workers_ai,
    run_translation_queue,
    _download_original,
    _official_document_fallbacks,
    _summarize_document,
    _checkpoint_identity,
    _checkpoint_key,
    _read_translation_checkpoint,
    _write_translation_checkpoint,
    SummaryFormatError,
    detect_language,
    is_safe_translated_key,
    parse_summary_response,
    process_pending_translations,
    queue_translation_backfill,
    render_norwegian_pdf,
    stable_chunks,
    validate_preserved_values,
)
from bemobi_news_translation import translate_bemobi_news  # noqa: E402


class TranslationUtilitiesTest(unittest.TestCase):
    def test_detects_portuguese_from_document_content(self) -> None:
        text = "A companhia informa aos acionistas que o conselho de administração aprovou ações."
        self.assertEqual(detect_language(text), "pt")

    def test_english_and_norwegian_do_not_require_translation(self) -> None:
        self.assertEqual(
            detect_language("The company and the board approved shares for investors."),
            "en",
        )
        self.assertEqual(
            detect_language("Selskapet og styret vedtok aksjer for eierne."), "nb"
        )

    def test_metadata_fallback_is_norwegian(self) -> None:
        title, summary = translate_bemobi_news(
            headline="original",
            summary=None,
            metadata={"cvm_category": "Reunião da Administração", "cvm_species": "Ata"},
        )
        self.assertEqual(title, "Styremøte — Protokoll")
        self.assertIn("Dokumenttype", summary or "")
        self.assertNotIn("Filing type", summary or "")

    def test_value_validation_catches_changed_number_percent_currency_and_date(
        self,
    ) -> None:
        original = "R$ 18,5 em 09/09/2026, tilsvarende 12,4 %."
        translated = "R$ 19,5 den 10/09/2026, tilsvarende 12,5 %."
        missing = validate_preserved_values(original, translated)
        self.assertIn("r$18,5", missing)
        self.assertIn("12,4%", missing)
        self.assertIn("09/09/2026", missing)

    def test_stable_chunks_keep_order_without_loss(self) -> None:
        text = "Første avsnitt.\n\nAndre avsnitt.\n\nTredje avsnitt."
        chunks = stable_chunks(text, limit=25)
        self.assertEqual(
            [item[0] for item in chunks], ["chunk-0001", "chunk-0002", "chunk-0003"]
        )
        self.assertEqual("\n\n".join(item[1] for item in chunks), text)

    def test_pdf_is_readable_and_marks_original_authoritative(self) -> None:
        payload = render_norwegian_pdf(
            "Styreprotokoll", "2026-09-09", "1. Vedtaket gjelder JCP."
        )
        extracted = "\n".join(
            page.extract_text() or "" for page in PdfReader(io.BytesIO(payload)).pages
        )
        self.assertIn("UOFFISIELL NORSK OVERSETTELSE", extracted)
        self.assertIn("autoritative kilden", extracted)

    def test_only_content_addressed_translation_keys_are_allowed(self) -> None:
        digest = "a" * 64
        self.assertTrue(
            is_safe_translated_key(f"translated/bemobi/{digest}/bemobi-norsk.pdf")
        )
        self.assertFalse(is_safe_translated_key("translated/bemobi/../../secret"))

    def test_summary_rejects_changed_field_types(self) -> None:
        with self.assertRaisesRegex(ValueError, "gyldig title-felt"):
            parse_summary_response(
                '{"title":["Styreprotokoll"],"summary":"Kort fortalt: Vedtak."}'
            )

        with self.assertRaisesRegex(ValueError, "gyldig summary-felt"):
            parse_summary_response('{"title":"Styreprotokoll","summary":null}')

    def test_summary_accepts_non_empty_string_fields(self) -> None:
        self.assertEqual(
            parse_summary_response(
                '{"title":" Styreprotokoll ","summary":" Kort fortalt: Vedtak. "}'
            ),
            ("Styreprotokoll", "Kort fortalt: Vedtak."),
        )


class SummaryRecoveryTest(unittest.IsolatedAsyncioTestCase):
    def test_fenced_json_accepted_but_arbitrary_prose_and_duplicate_keys_rejected(self):
        valid = '{"title":"Tittel","summary":"Kort fortalt: Vedtak."}'
        self.assertEqual(parse_summary_response("```json\n" + valid + "\n```"),
                         ("Tittel", "Kort fortalt: Vedtak."))
        for bad in ("Forklaring: " + valid, '{"title":"A","title":"B","summary":"C"}',
                    '{"title":"A","summary":"B","extra":1}'):
            with self.assertRaises(SummaryFormatError):
                parse_summary_response(bad)

    async def test_summary_retries_format_once_using_original_text(self):
        class Provider:
            model = "test"
            def __init__(self):
                self.calls = []
            async def complete(self, instruction, text):
                self.calls.append((instruction, text))
                return ("ugyldig" if len(self.calls) == 1
                        else '{"title":"Tittel","summary":"Kort fortalt: Vedtak."}')
        provider = Provider()
        self.assertEqual(await _summarize_document(provider, "Original"),
                         ("Tittel", "Kort fortalt: Vedtak."))
        self.assertEqual([text for _, text in provider.calls], ["Original", "Original"])

    async def test_checkpoint_revalidates_identity_hash_and_values(self):
        class Bucket:
            def __init__(self):
                self.objects = {}
            async def put(self, key, raw, **kwargs):
                self.objects[key] = raw
            async def get(self, key):
                if key not in self.objects:
                    return None
                raw = self.objects[key]
                async def body():
                    return raw
                return SimpleNamespace(size=len(raw), arrayBuffer=body)
        bucket = Bucket()
        original = "A companhia tem 123 ações."
        identity = _checkpoint_identity("a" * 64, original, "model")
        translated = "Selskapet har 123 aksjer."
        await _write_translation_checkpoint(bucket, identity, translated)
        self.assertEqual(await _read_translation_checkpoint(bucket, identity, original), translated)
        self.assertFalse(is_safe_translated_key(_checkpoint_key(identity)))
        other = _checkpoint_identity("a" * 64, original, "other-model")
        self.assertIsNone(await _read_translation_checkpoint(bucket, other, original))
        raw = json.loads(bucket.objects[_checkpoint_key(identity)])
        raw["translation"] = "Selskapet har 124 aksjer."
        raw["translation_sha256"] = hashlib.sha256(raw["translation"].encode()).hexdigest()
        bucket.objects[_checkpoint_key(identity)] = json.dumps(raw).encode()
        self.assertIsNone(await _read_translation_checkpoint(bucket, identity, original))

    async def test_document_retry_reuses_translation_after_summary_error(self):
        class Bucket:
            def __init__(self):
                self.objects = {}
            async def put(self, key, raw, **kwargs):
                self.objects[key] = raw
            async def get(self, key):
                if key not in self.objects:
                    return None
                raw = self.objects[key]
                async def body():
                    return raw
                return SimpleNamespace(size=len(raw), arrayBuffer=body)
        class Repository:
            def __init__(self):
                self.updates = []
            async def all(self, query, parameters):
                return [{"id": 9, "url": "https://example.com/a.pdf", "published_at": "2026-11-27",
                         "source_code": "CVM", "translation_attempts": 0}]
            async def first(self, query, parameters):
                return None
            async def run(self, query, parameters):
                self.updates.append((query, parameters))
                return SimpleNamespace(meta=SimpleNamespace(changes=1))
        class Provider:
            model = "test"
            def __init__(self):
                self.translations = 0
                self.summaries = 0
            async def complete(self, instruction, text):
                if instruction.startswith("Oversett hele"):
                    self.translations += 1
                    return "Selskapet har 123 aksjer. " * 10
                self.summaries += 1
                return ("ugyldig" if self.summaries <= 2 else
                        '{"title":"Tittel","summary":"Kort fortalt: Selskapet har 123 aksjer."}')
        async def fetcher(*args, **kwargs):
            async def body():
                return b"%PDF-test"
            return SimpleNamespace(ok=True, headers={}, arrayBuffer=body)
        repository, bucket, provider = Repository(), Bucket(), Provider()
        first, second = [], []
        with patch("bemobi_document_translation.extract_pdf_text",
                   return_value="A companhia informa que tem 123 ações. " * 10):
            result = await process_pending_translations(repository, bucket, provider,
                                                        fetcher=fetcher, diagnostics=first)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(first[0]["summary_error"], "invalid_json")
            self.assertEqual(first[0]["translation_checkpoint"], "saved")
            result = await process_pending_translations(repository, bucket, provider,
                                                        fetcher=fetcher, diagnostics=second)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(second[0]["translation_checkpoint"], "reused")
        self.assertEqual(provider.translations, 1)
        self.assertEqual(provider.summaries, 3)


class FakeWorkersAI:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def run(self, model: str, inputs: dict[str, object]) -> object:
        self.calls.append((model, inputs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class WorkersAIProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_native_workers_ai_binding_is_used_without_api_key(self) -> None:
        ai = FakeWorkersAI({"response": "Norsk oversettelse"})
        provider = WorkersAIProvider(ai=ai, model=DEFAULT_WORKERS_AI_MODEL)

        result = await provider.complete("Oversett til norsk", "Texto português")

        self.assertEqual(result, "Norsk oversettelse")
        self.assertEqual(ai.calls[0][0], "@cf/google/gemma-4-26b-a4b-it")
        messages = ai.calls[0][1]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["content"], "Texto português")
        self.assertEqual(ai.calls[0][1]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(ai.calls[0][1]["max_completion_tokens"], 4096)
        self.assertNotIn("max_tokens", ai.calls[0][1])
        self.assertNotIn("api_key", provider.__dataclass_fields__)

    async def test_chat_completion_response_and_truncation(self) -> None:
        provider = WorkersAIProvider(FakeWorkersAI({"choices": [{
            "finish_reason": "stop", "message": {"content": "Norsk tekst"}}]}), DEFAULT_WORKERS_AI_MODEL)
        self.assertEqual(await provider.complete("Oversett", "Texto"), "Norsk tekst")
        provider = WorkersAIProvider(FakeWorkersAI({"choices": [{
            "finish_reason": "length", "message": {"content": "Avkortet tekst"}}]}), DEFAULT_WORKERS_AI_MODEL)
        with self.assertRaisesRegex(RuntimeError, "fullførte ikke"):
            await provider.complete("Oversett", "Texto")

    async def test_summary_json_is_returned_unchanged(self) -> None:
        summary = '{"title":"Styreprotokoll","summary":"Kort fortalt: Vedtak."}'
        provider = WorkersAIProvider(
            ai=FakeWorkersAI({"response": summary}), model=DEFAULT_WORKERS_AI_MODEL
        )

        self.assertEqual(await provider.complete("Oppsummer", "Dokument"), summary)

    async def test_rate_limit_is_propagated_to_document_error_handling(self) -> None:
        provider = WorkersAIProvider(
            ai=FakeWorkersAI(RuntimeError("rate limit")),
            model=DEFAULT_WORKERS_AI_MODEL,
        )

        with self.assertRaisesRegex(RuntimeError, "rate limit"):
            await provider.complete("Oversett", "Dokument")

    async def test_invalid_workers_ai_response_fails_clearly(self) -> None:
        provider = WorkersAIProvider(
            ai=FakeWorkersAI({"unexpected": "value"}), model=DEFAULT_WORKERS_AI_MODEL
        )

        with self.assertRaisesRegex(RuntimeError, "tomt eller ugyldig"):
            await provider.complete("Oversett", "Dokument")


class AIProductionProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_synthetic_probe_uses_real_binding_without_document(self):
        ai = FakeWorkersAI({"choices": [{"finish_reason": "stop",
                         "message": {"content": "Selskapet har 123 aksjer."}}]})
        result = await probe_workers_ai(WorkersAIProvider(ai, DEFAULT_WORKERS_AI_MODEL))
        self.assertEqual(result, {"status": "ok", "binding_calls": 1})
        self.assertEqual(ai.calls[0][1]["max_completion_tokens"], 128)

    async def test_probe_failure_does_not_claim_any_document(self):
        class Repository:
            def __init__(self):
                self.writes = []
            async def first(self, query, parameters):
                if "SELECT sd.id" in query:
                    return {"id": 9}
                return {"pending": 7, "failed": 3, "exhausted": 1, "overdue": 7}
            async def run(self, *args):
                self.writes.append(args)
                raise AssertionError("No write permitted on failed probe")
            async def all(self, *args):
                raise AssertionError("No document selection permitted on failed probe")
        repository = Repository()
        ai = FakeWorkersAI(RuntimeError("InferenceError: 3036: daily quota secret"))
        result = await run_translation_queue(repository, SimpleNamespace(),
                                             WorkersAIProvider(ai, DEFAULT_WORKERS_AI_MODEL))
        self.assertEqual(result["selected"], 0)
        self.assertEqual(result["ai_probe"]["error"]["code"], 3036)
        self.assertEqual(result["ai_probe"]["error"]["category"], "quota")
        self.assertEqual(result["status"], "partial")
        self.assertNotIn("secret", str(result))
        self.assertEqual(repository.writes, [])


class OriginalFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_cvm_alternate_preserves_exact_filing_identity(self):
        from bemobi_cvm_rad import filing_identity
        url = ("https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?"
               "CodigoInstituicao=1&Tela=ext&descTipo=IPE&numProtocolo=12&numSequencia=34&numVersao=2")
        alternate = _official_document_fallbacks(url)[0]
        self.assertNotEqual(url, alternate)
        self.assertEqual(filing_identity(url), filing_identity(alternate))
        calls = []

        async def fetcher(candidate, **kwargs):
            calls.append(candidate)
            if candidate == url:
                return SimpleNamespace(ok=False, status=526)
            async def body():
                return b"%PDF-1.4 test"
            return SimpleNamespace(ok=True, headers={}, arrayBuffer=body)

        trace = {"downloads": []}
        self.assertEqual(await _download_original(url, None, fetcher, trace=trace), b"%PDF-1.4 test")
        self.assertEqual(trace["downloads"], [{"route": "original", "result": "http_error", "http": 526},
                                              {"route": "official_alternative", "result": "ok"}])
        self.assertEqual(calls, [url, alternate])
        self.assertEqual(_official_document_fallbacks("https://example.com/a.pdf"), [])

    async def test_summary_is_bounded_and_all_sections_are_used(self):
        class Provider:
            def __init__(self):
                self.calls = []
            async def complete(self, instruction, text):
                self.calls.append(text)
                return '{"title":"Tittel","summary":"Kort fortalt: Sammendrag."}'
        provider = Provider()
        await _summarize_document(provider, "A" * 48_000 + "B" * 48_000)
        self.assertEqual(provider.calls[:2], ["A" * 48_000, "B" * 48_000])
        self.assertEqual(len(provider.calls), 3)
        self.assertTrue(all(len(x) <= 48_000 for x in provider.calls))


class TranslationRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_stale_processing_document_is_selected_but_recent_one_is_not(
        self,
    ) -> None:
        class Repository:
            def __init__(self) -> None:
                self.connection = sqlite3.connect(":memory:")
                self.connection.row_factory = sqlite3.Row
                self.connection.executescript("""
                    CREATE TABLE sources (id INTEGER PRIMARY KEY, code TEXT);
                    CREATE TABLE source_documents (
                        id INTEGER PRIMARY KEY,
                        source_id INTEGER,
                        url TEXT,
                        title TEXT,
                        published_at TEXT,
                        content_sha256 TEXT,
                        translation_status TEXT,
                        translation_processed_at TEXT,
                        translation_attempts INTEGER NOT NULL DEFAULT 0
                    );
                    INSERT INTO sources VALUES (1, 'CVM');
                    INSERT INTO source_documents (id,source_id,url,title,published_at,content_sha256,translation_status,translation_processed_at) VALUES (
                        1, 1, 'https://example.com/old.pdf', 'Gammel', NULL, NULL,
                        'PROCESSING', strftime('%Y-%m-%dT%H:%M:%fZ','now','-7 hours')
                    );
                    INSERT INTO source_documents (id,source_id,url,title,published_at,content_sha256,translation_status,translation_processed_at) VALUES (
                        2, 1, 'https://example.com/new.pdf', 'Ny', NULL, NULL,
                        'PROCESSING', strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    );
                    INSERT INTO source_documents
                        (id,source_id,url,title,translation_status,translation_processed_at,translation_attempts)
                        VALUES
                        (3,1,'https://example.com/failed.pdf','Feilet','FAILED',strftime('%Y-%m-%dT%H:%M:%fZ','now','-7 hours'),1),
                        (4,1,'https://example.com/recent.pdf','Nylig','FAILED',strftime('%Y-%m-%dT%H:%M:%fZ','now'),1),
                        (5,1,'https://example.com/exhausted.pdf','Oppbrukt','FAILED',strftime('%Y-%m-%dT%H:%M:%fZ','now','-7 hours'),3),
                        (6,1,'https://example.com/retry.pdf','Vent','PENDING',strftime('%Y-%m-%dT%H:%M:%fZ','now'),1);
                    """)

            async def all(self, query: str, parameters: tuple[object, ...]):
                return [
                    dict(row)
                    for row in self.connection.execute(query, parameters).fetchall()
                ]

            async def run(self, query: str, parameters: tuple[object, ...]):
                return SimpleNamespace(meta=SimpleNamespace(changes=0))

        result = await process_pending_translations(
            Repository(), SimpleNamespace(), FakeWorkersAI({"response": "ubrukt"})
        )

        self.assertEqual(result, {"selected": 2, "completed": 0, "failed": 0})

    async def test_rate_limit_keeps_document_pending_for_next_run(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.updates: list[tuple[str, tuple[object, ...]]] = []

            async def all(self, query: str, parameters: tuple[object, ...]):
                return [
                    {
                        "id": 9,
                        "url": "https://example.com/document.pdf",
                        "title": "Dokument",
                        "published_at": "2026-09-09",
                        "content_sha256": None,
                    }
                ]

            async def first(self, query: str, parameters: tuple[object, ...]):
                return None

            async def run(self, query: str, parameters: tuple[object, ...]):
                self.updates.append((query, parameters))
                return SimpleNamespace(meta=SimpleNamespace(changes=1))

        async def fetcher(*args: object, **kwargs: object) -> SimpleNamespace:
            async def array_buffer() -> bytes:
                return b"%PDF test"

            return SimpleNamespace(ok=True, headers={}, arrayBuffer=array_buffer)

        repository = Repository()
        provider = WorkersAIProvider(
            ai=FakeWorkersAI(RuntimeError("rate limit")),
            model=DEFAULT_WORKERS_AI_MODEL,
        )
        diagnostics = []
        with patch(
            "bemobi_document_translation.extract_pdf_text",
            return_value="A companhia e os acionistas " * 10,
        ):
            result = await process_pending_translations(
                repository,
                SimpleNamespace(),
                provider,
                fetcher=fetcher,
                diagnostics=diagnostics,
            )

        self.assertEqual(result, {"selected": 1, "completed": 0, "failed": 1})
        self.assertEqual(diagnostics[0]["stage"], "translation")
        self.assertEqual(diagnostics[0]["ai_provider_calls"], 1)
        self.assertEqual(diagnostics[0]["ai_binding_calls"], 1)
        self.assertEqual(diagnostics[0]["ai_responses"], 0)
        self.assertEqual(diagnostics[0]["downloads"][0]["result"], "ok")
        final_query, final_parameters = repository.updates[-1]
        self.assertIn("translation_status='PENDING'", final_query)
        self.assertEqual(final_parameters, ("translation:WorkersAIError: ai_category=quota; ai_code=0; ai_http=0", 9))


class FakeRepository:
    def __init__(self, document_ids: list[int] | None = None) -> None:
        self.document_ids = [9] if document_ids is None else document_ids
        self.updates: list[tuple[str, tuple[object, ...]]] = []

    async def all(self, query: str, parameters: tuple[object, ...]):
        self.query = query
        self.parameters = parameters
        return [{"id": document_id} for document_id in self.document_ids]

    async def run(self, query: str, parameters: tuple[object, ...]):
        self.updates.append((query, parameters))


class BackfillTest(unittest.IsolatedAsyncioTestCase):
    async def test_backfill_respects_document_date_and_limit(self) -> None:
        repository = FakeRepository()
        count = await queue_translation_backfill(
            repository, document_id=9, after="2026-01-01", limit=1
        )
        self.assertEqual(count, 1)
        self.assertIn("sd.id=?", repository.query)
        self.assertIn("substr(sd.published_at,1,10)>=?", repository.query)
        self.assertEqual(repository.parameters, (9, "2026-01-01", 1))
        self.assertEqual(repository.updates[0][1], (9,))

    async def test_backfill_queues_one_hundred_documents_in_one_write(self) -> None:
        document_ids = list(range(1, 101))
        repository = FakeRepository(document_ids)

        count = await queue_translation_backfill(repository, limit=100)

        self.assertEqual(count, 100)
        self.assertEqual(len(repository.updates), 1)
        query, parameters = repository.updates[0]
        self.assertEqual(query.count("?"), 100)
        self.assertEqual(parameters, tuple(document_ids))


if __name__ == "__main__":
    unittest.main()


class ChunkValueRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_retry_preserves_exact_original_values(self):
        from bemobi_document_translation import translate_verified_chunk
        class Provider:
            async def complete(self, instruction, text):
                self.calls = getattr(self,"calls",0)+1
                assert text == "A companhia tem 123 ações, R$ 18,5."
                return "Selskapet har 124 aksjer." if self.calls == 1 else "Selskapet har 123 aksjer, R$ 18,5."
        trace={}
        result=await translate_verified_chunk(Provider(),"chunk-0001","A companhia tem 123 ações, R$ 18,5.",trace)
        self.assertIn("123",result)
        self.assertEqual(trace["value_chunk_retries"],1)

    async def test_failed_retry_rejects_instead_of_publishing(self):
        from bemobi_document_translation import translate_verified_chunk, ValuePreservationError
        class Provider:
            async def complete(self,instruction,text):
                return "Selskapet har 124 aksjer."
        trace={}
        with self.assertRaises(ValuePreservationError):
            await translate_verified_chunk(Provider(),"chunk-0001","A companhia tem 123 ações.",trace)
        self.assertEqual(trace["value_missing_count"],1)
        self.assertEqual(trace["value_chunk_retries"],1)


class BoundedDocumentProgressTest(unittest.IsolatedAsyncioTestCase):
    async def test_large_document_resumes_only_verified_parts(self):
        from bemobi_document_translation import _translate_document_parts

        class Bucket:
            def __init__(self):
                self.objects = {}
            async def put(self, key, raw, **kwargs):
                self.objects[key] = raw
            async def get(self, key):
                raw = self.objects.get(key)
                if raw is None:
                    return None
                async def body():
                    return raw
                return SimpleNamespace(size=len(raw), arrayBuffer=body)

        class Provider:
            model = "test"
            def __init__(self):
                self.calls = []
            async def complete(self, instruction, text):
                self.calls.append(text)
                return text.replace("A companhia", "Selskapet")

        chunks = [(f"chunk-{i:04d}", f"A companhia tem {i} ações.") for i in range(1, 9)]
        text = "\n\n".join(chunk for _, chunk in chunks)
        identity = _checkpoint_identity("a" * 64, text, "test")
        bucket, provider, trace = Bucket(), Provider(), {}
        with patch("bemobi_document_translation.MAX_NEW_CHUNKS_PER_CLAIM", 3):
            self.assertIsNone(await _translate_document_parts(bucket, identity, chunks, provider, trace))
            self.assertEqual(len(provider.calls), 3)
            self.assertEqual(trace["parts_saved"], 3)
            self.assertIsNone(await _translate_document_parts(bucket, identity, chunks, provider, trace))
            self.assertEqual(len(provider.calls), 6)
            self.assertEqual(trace["parts_reused"], 3)
            translated = await _translate_document_parts(bucket, identity, chunks, provider, trace)
        self.assertEqual(len(provider.calls), 8)
        self.assertEqual(trace["parts_reused"], 6)
        self.assertEqual(validate_preserved_values(text, translated), [])
        self.assertTrue(all(not is_safe_translated_key(key) for key in bucket.objects))
        # Tampered checkpoint must not be accepted even with a matching hash.
        key = next(iter(bucket.objects))
        raw = json.loads(bucket.objects[key])
        raw["translation"] = "Selskapet har 999 aksjer."
        raw["translation_sha256"] = hashlib.sha256(raw["translation"].encode()).hexdigest()
        bucket.objects[key] = json.dumps(raw).encode()
        await _translate_document_parts(bucket, identity, chunks, provider, {})
        self.assertEqual(len(provider.calls), 9)

    async def test_smaller_parts_recover_without_weakening_value_validation(self):
        from bemobi_document_translation import translate_verified_chunk
        original = ("A companhia informa R$ 123,45 e 12,4 % em 09/09/2026. " * 30).strip()
        class Provider:
            async def complete(self, instruction, text):
                if len(text) > 1000:
                    return "Selskapet har ingen verdier."
                return text.replace("A companhia", "Selskapet")
        trace = {}
        translated = await translate_verified_chunk(Provider(), "chunk-0001", original, trace)
        self.assertEqual(validate_preserved_values(original, translated), [])
        self.assertGreater(trace["value_chunk_splits"], 0)

    async def test_progress_releases_claim_without_consuming_failed_attempt(self):
        class Repository:
            def __init__(self):
                self.updates = []
            async def all(self, query, parameters):
                return [{"id": 9, "url": "https://example.com/a.pdf", "published_at": "2026-11-27",
                         "source_code": "CVM", "translation_attempts": 2}]
            async def first(self, query, parameters):
                return None
            async def run(self, query, parameters):
                self.updates.append((query, parameters))
                return SimpleNamespace(meta=SimpleNamespace(changes=1))

        class Provider:
            model = "test"
        async def fetcher(*args, **kwargs):
            async def body():
                return b"%PDF-test"
            return SimpleNamespace(ok=True, headers={}, arrayBuffer=body)
        repository, diagnostics = Repository(), []
        with patch("bemobi_document_translation.extract_pdf_text",
                   return_value="A companhia informa que tem 123 ações. " * 10), \
             patch("bemobi_document_translation._translate_document_parts", return_value=None):
            result = await process_pending_translations(repository, SimpleNamespace(), Provider(),
                                                        fetcher=fetcher, diagnostics=diagnostics)
        self.assertEqual(result, {"selected": 1, "completed": 0, "failed": 0, "deferred": 1})
        query, params = repository.updates[-1]
        self.assertIn("translation_attempts=translation_attempts-1", query)
        self.assertIn("translation_status='PENDING'", query)
        self.assertEqual(params, (9, 3))
        self.assertEqual(diagnostics[0]["outcome"], "progress")

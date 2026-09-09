from __future__ import annotations

import io
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
    detect_language,
    is_safe_translated_key,
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
        self.assertEqual(ai.calls[0][0], "@cf/meta/llama-3.1-8b-instruct")
        messages = ai.calls[0][1]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["content"], "Texto português")
        self.assertNotIn("api_key", provider.__dataclass_fields__)

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


class TranslationRetryTest(unittest.IsolatedAsyncioTestCase):
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
        with patch(
            "bemobi_document_translation.extract_pdf_text",
            return_value="A companhia e os acionistas " * 10,
        ):
            result = await process_pending_translations(
                repository,
                SimpleNamespace(),
                provider,
                fetcher=fetcher,
            )

        self.assertEqual(result, {"selected": 1, "completed": 0, "failed": 1})
        final_query, final_parameters = repository.updates[-1]
        self.assertIn("translation_status='PENDING'", final_query)
        self.assertEqual(final_parameters, ("rate limit", 9))


class FakeRepository:
    def __init__(self) -> None:
        self.updates: list[tuple[str, tuple[object, ...]]] = []

    async def all(self, query: str, parameters: tuple[object, ...]):
        self.query = query
        self.parameters = parameters
        return [{"id": 9}]

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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

from pypdf import PdfReader

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from bemobi_document_translation import (  # noqa: E402
    detect_language,
    is_safe_translated_key,
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

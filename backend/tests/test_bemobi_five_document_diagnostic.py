from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from diagnose_bemobi_five_documents import IDS, SQL, classify_error, source_metrics


def test_fixed_scope_and_redaction():
    assert IDS == (7538, 7537, 5282, 1475, 292)
    assert SQL.lstrip().startswith("SELECT")
    assert classify_error("translation:ValueError: Dokumentet overskrider sikker behandlingsgrense") == {"reason": "max_document_chunks"}
    assert classify_error("value_validation:ValuePreservationError: verdikontroll feilet (8 mangler) secret") == {"reason": "missing_values", "missing_count": 8}
    assert classify_error("translation:WorkersAIError: ai_code=3036; secret") == {"reason": "ai_error", "ai_code": 3036}
    assert classify_error("translation:WorkersAIError: ai_code=9999; secret") == {"reason": "ai_error", "ai_code": None}
    assert classify_error("secret URL") == {"reason": "unknown"}


def test_metrics_detect_document_limit_and_preexisting_chunk_split():
    from bemobi_document_translation import MAX_DOCUMENT_CHUNKS, MAX_CHUNK_CHARACTERS

    # Test the exact current boundary, rather than the retired 40-part limit.
    at_limit = source_metrics("a" * (MAX_DOCUMENT_CHUNKS * MAX_CHUNK_CHARACTERS))
    assert at_limit["chunks"] == MAX_DOCUMENT_CHUNKS
    assert at_limit["chunk_limit"] == MAX_DOCUMENT_CHUNKS
    assert not at_limit["exceeds_limit"]
    over_limit = source_metrics("a" * (MAX_DOCUMENT_CHUNKS * MAX_CHUNK_CHARACTERS + 1))
    assert over_limit["chunks"] == MAX_DOCUMENT_CHUNKS + 1
    assert over_limit["exceeds_limit"]
    # Previously oversized documents must now be within the total safety limit.
    historical = source_metrics("de da do " + "a" * 170000)
    assert historical["chunks"] > 40
    assert not historical["exceeds_limit"]
    # Boundary crosses a financial number even before AI has translated it.
    metrics = source_metrics("a" * 3996 + " 1234567")
    assert metrics["values_lost_by_chunking"] == 1
    assert not metrics["exceeds_limit"]

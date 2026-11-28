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
    metrics = source_metrics("de da do " + "a" * 170000)
    assert metrics["exceeds_limit"]
    assert metrics["chunks"] > 40
    # Boundary crosses a financial number even before AI has translated it.
    metrics = source_metrics("a" * 3996 + " 1234567")
    assert metrics["values_lost_by_chunking"] == 1
    assert not metrics["exceeds_limit"]

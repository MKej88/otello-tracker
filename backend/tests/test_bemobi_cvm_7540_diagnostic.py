"""Offline tests for read-only, body-free CVM file-format diagnostics."""
import io
import json
import sys
from pathlib import Path

from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from diagnose_bemobi_cvm_7540 import inspect_body, SQL, DOCUMENT_ID


def test_html_disguised_as_pdf_is_not_accepted():
    raw = b"<!DOCTYPE html><html>private sample</html>"
    result = inspect_body(raw, "application/pdf", len(raw))
    assert result["mime"] == "application/pdf"
    assert result["body_kind"] == "html"
    assert not result["strict_integrity"]
    assert result["parser"] == "not_attempted"
    assert "private sample" not in json.dumps(result)


def test_missing_or_distant_eof_remains_invalid():
    for raw in (b"%PDF-1.4\nmissing", b"%PDF-1.4\n%%EOF" + b" " * 3000):
        result = inspect_body(raw, "application/pdf")
        assert result["header_at_start"]
        assert not result["eof_in_last_2048"]
        assert not result["strict_integrity"]
    assert not inspect_body(b"prefix%PDF-1.4\n%%EOF", "text/plain")["strict_integrity"]


def test_real_pdf_passes_both_checks():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    raw = stream.getvalue()
    result = inspect_body(raw, "application/pdf", len(raw))
    assert result["strict_integrity"]
    assert result["parser"] == "readable"
    assert result["pages"] == 1
    assert result["content_length_matches"]


def test_scope_and_no_write_permissions():
    assert DOCUMENT_ID == 7540
    assert "sd.id=?" in SQL
    assert "UPDATE" not in SQL
    workflow = (ROOT / ".github/workflows/bemobi-cvm-7540-diagnostic.yml").read_text()
    assert "CLOUDFLARE_READ_TOKEN" in workflow
    assert "CLOUDFLARE_API_TOKEN" not in workflow
    assert "upload-artifact" not in workflow

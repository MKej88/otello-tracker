"""Offline tests for read-only, body-free CVM file-format diagnostics."""
import io
import json
import sys
from pathlib import Path

from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from diagnose_bemobi_cvm_7540 import inspect_body, inspect_tail, SQL, DOCUMENT_ID


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


def test_tail_padding_and_html_are_distinguished_without_exposing_contents():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    core = stream.getvalue()
    padding, _ = inspect_tail(core + b" " * 3000)
    assert padding["category"] == "padding_only"
    assert padding["tail_nonpadding_bytes"] == 0
    html, fingerprint = inspect_tail(core + b"<html>private marker</html>" + b" " * 3000)
    assert html["category"] == "html_markers"
    assert html["tail_markers"]["html"]
    assert html["eof_prefix_pdf"]["status"] == "readable"
    assert html["same_page_count"]
    assert html["same_extracted_text"]
    assert "private marker" not in json.dumps(html)
    assert fingerprint[0] == inspect_tail(core)[1][0]


def test_signature_and_pdf_object_markers_are_hints_not_approval():
    prefix = b"%PDF-1.4\n%%EOF"
    cms = b"\x30\x0b\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x07\x02"
    report, _ = inspect_tail(prefix + cms)
    assert report["category"] == "possible_cms"
    assert report["der_sequence_consumes_tail"]
    assert report["tail_markers"]["cms_signed_data_oid"]
    report, _ = inspect_tail(prefix + b"\n4 0 obj\n/Type /Sig\n/ByteRange [0 1 2 3]\n")
    assert report["category"] == "pdf_structure_present"
    assert report["tail_markers"]["pdf_byte_range"]
    assert report["tail_markers"]["pdf_signature_type"]
    assert inspect_tail(b"not a PDF")[0]["status"] == "not_applicable"

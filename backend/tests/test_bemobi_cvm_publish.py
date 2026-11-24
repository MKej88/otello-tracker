"""Regression checks: single-download publisher and bounded retries."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import urllib.error
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "cloudflare" / "src"))
import mirror_bemobi_cvm_live as mirror
from bemobi_cvm_rad import parse_rows, release_candidates, filing_identity

def test_transient_non_pdf_is_retried():
    responses = iter([b"<html>temporary upstream error</html>", b"%PDF-verified"])
    pauses = []
    raw = mirror.download_pdf(None, "https://example.invalid", reader=lambda *a, **kw: next(responses), sleeper=pauses.append)
    assert raw == b"%PDF-verified"
    assert pauses == [2]

def test_three_attempt_limit():
    attempts = []
    def invalid(*args, **kwargs):
        attempts.append(1)
        return b"<html>temporary error</html>"
    with pytest.raises(ValueError, match="three attempts"):
        mirror.download_pdf(None, "https://example.invalid", reader=invalid, sleeper=lambda _: None)
    assert len(attempts) == 3

def test_access_challenge_is_not_retried():
    with pytest.raises(ValueError, match="access challenge"):
        mirror.download_pdf(None, "https://example.invalid", reader=lambda *a, **kw: b"captcha", sleeper=lambda _: pytest.fail("must not retry"))

def test_forbidden_is_not_retried():
    def forbidden(*a, **kw):
        raise urllib.error.HTTPError("https://example.invalid", 403, "forbidden", None, None)
    with pytest.raises(urllib.error.HTTPError):
        mirror.download_pdf(None, "https://example.invalid", reader=forbidden, sleeper=lambda _: pytest.fail("must not retry"))

def test_verify_bundle_rejects_tampering(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    end = now.date()
    start = end - timedelta(days=120)
    delivery = end.strftime("%d/%m/%Y")
    fields = ["BEMOBI MOBILE TECH S.A.", "025500", "Dados Economico-Financeiros",
              "Press-release", "Release 3T26", delivery, delivery, "Ativo",
              "", "EN", "OpenDownloadDocumentos('456','1','123','IPE')", "Release 3T26"]
    listing = {"d": {"temErro": False, "dados": "$&".join(fields)}}
    row = release_candidates(parse_rows(listing, start, end))[0]
    raw = b"%PDF-validated fixture"
    digest = hashlib.sha256(raw).hexdigest()
    key = mirror.pdf_key(filing_identity(row["url"]), digest)
    artifact = dict(url=row["url"], period="3Q26", sha256=digest, bytes=len(raw), key=key)
    index = dict(schema=1, cvm_code="25500", observed_at=now.isoformat(),
                 start_date=start.isoformat(), end_date=end.isoformat(), listing=listing, artifact=artifact)
    (tmp_path / "latest.json").write_text(json.dumps(index))
    (tmp_path / "release.pdf").write_bytes(raw)
    (tmp_path / "key.txt").write_text(key)
    monkeypatch.setattr(mirror, "_pdf_text", lambda _: "report")
    monkeypatch.setattr(mirror, "parse_bemobi_result_text", lambda *a, **kw: {"period": "3Q26"})
    monkeypatch.setattr(mirror, "read", lambda *a, **kw: pytest.fail("No external request"))
    mirror.verify_bundle(tmp_path)
    (tmp_path / "release.pdf").write_bytes(b"%PDF-tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        mirror.verify_bundle(tmp_path)

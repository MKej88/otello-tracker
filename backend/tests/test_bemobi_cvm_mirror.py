"""Checks for provenance, freshness, integrity and fallback in the private CVM mirror."""
import asyncio
import hashlib
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cloudflare" / "src"))
from bemobi_cvm_rad import parse_rows, release_candidates, filing_identity
from bemobi_cvm_mirror import INDEX, pdf_key, validate_index, discover_mirrored_releases

NOW = datetime(2026,11,24,3,tzinfo=UTC)
RAW = b"%PDF-1.6 test fixture"
def fixture():
    fields = ["BEMOBI MOBILE TECH S.A.", "025500", "Dados Economico-Financeiros",
              "Press-release", "Release 3T26", "30/09/2026", "12/11/2026", "Ativo",
              "", "EN", "OpenDownloadDocumentos('456','1','123','IPE')", "Release 3T26"]
    listing = {"d": {"temErro": False, "dados": "$&".join(fields)}}
    start = NOW.date() - timedelta(days=120)
    row = release_candidates(parse_rows(listing, start, NOW.date()))[0]
    digest = hashlib.sha256(RAW).hexdigest()
    artifact = dict(url=row["url"], period="3Q26", sha256=digest, bytes=len(RAW),
                    key=pdf_key(filing_identity(row["url"]), digest))
    return dict(schema=1, cvm_code="25500", observed_at=NOW.isoformat(),
                start_date=start.isoformat(), end_date=NOW.date().isoformat(),
                listing=listing, artifact=artifact)

class Object:
    def __init__(self, raw):
        self.raw = raw
        self.size = len(raw)
    async def arrayBuffer(self):
        return self.raw

class Bucket:
    def __init__(self, index, raw=RAW):
        self.objects = {INDEX: json.dumps(index).encode(), index["artifact"]["key"]: raw}
    async def get(self, key):
        raw = self.objects.get(key)
        return Object(raw) if raw else None

def test_verified_fresh_mirror():
    rows, status = asyncio.run(discover_mirrored_releases(Bucket(fixture()),
        target_date="2026-11-23", now=NOW))
    assert rows[0]["expected_period"] == "3Q26"
    assert status["transport"] == "github_actions_private_r2"
    assert status["status"] == "ok"

def test_corrupt_pdf_rejected():
    rows, status = asyncio.run(discover_mirrored_releases(Bucket(fixture(), b"%PDF-bad"),
        target_date="2026-11-23", now=NOW))
    assert rows == [] and status["status"] == "not_available"

def test_stale_or_historical_manifest_rejected():
    for target, now in (("2026-11-21", NOW), ("2026-11-24", NOW + timedelta(days=2))):
        with pytest.raises(ValueError):
            validate_index(fixture(), target_date=target, now=now)

def test_wrong_filing_identity_rejected():
    index = fixture()
    index["artifact"]["url"] = "https://example.com/report.pdf"
    with pytest.raises(ValueError):
        validate_index(index, target_date="2026-11-23", now=NOW)

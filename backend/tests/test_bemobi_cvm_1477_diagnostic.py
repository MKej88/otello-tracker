import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import diagnose_bemobi_cvm_1477 as diagnostic


def test_exact_scope_and_read_only_permissions(tmp_path, monkeypatch):
    assert diagnostic.DOCUMENT_ID == 1477
    assert "sd.id=?" in diagnostic.SQL
    def client(token):
        assert token == "CLOUDFLARE_READ_TOKEN"
        def query(sql, params):
            assert sql == diagnostic.SQL and params == (1477,)
            return {"results": [{"document_id": 1477, "url": "test", "delivery": "2026-11-01"}]}
        return query
    monkeypatch.setattr(diagnostic, "d1_client", client)
    diagnostic.collect(tmp_path)
    path = tmp_path / "filing.json"
    assert json.loads(path.read_text())["document_id"] == 1477
    path.write_text(json.dumps({"document_id": 7540}))
    with pytest.raises(ValueError, match="Uventet dokument-ID"):
        diagnostic.diagnose(tmp_path)
    workflow = (ROOT / ".github/workflows/bemobi-cvm-1477-diagnostic.yml").read_text()
    assert "CLOUDFLARE_READ_TOKEN" in workflow
    assert "CLOUDFLARE_API_TOKEN" not in workflow
    assert "upload-artifact" not in workflow

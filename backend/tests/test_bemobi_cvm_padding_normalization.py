import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools"))
from test_bemobi_translation_mirror import fixture, IDENTITY, DELIVERY
from test_bemobi_7540_normalization import sample_pdf
from bemobi_cvm_padding_normalization import build_manifest, validate_manifest, verify_manifest_pair
from bemobi_translation_mirror import manifest_key, official_urls, read_translation_mirror, verify_pdf
from bemobi_document_translation import _download_original
from mirror_bemobi_translation_queue import write_local_pair, verify_local_pair


def test_two_official_routes_and_immutable_original(tmp_path):
    core = sample_pdf()
    alternative = core + b"\0"*31167
    canonical = alternative + b"canonical metadata"
    manifest, processing = build_manifest(IDENTITY, DELIVERY, fixture()["listing"], canonical, alternative)
    assert manifest["schema"] == 2
    assert processing == core[:core.rfind(b"%%EOF")+5]+b"\n"
    assert verify_manifest_pair(manifest, alternative, processing) == processing
    write_local_pair(tmp_path, manifest, alternative)
    assert (tmp_path/"original.pdf").read_bytes() == alternative
    assert (tmp_path/"processing.pdf").read_bytes() == processing
    assert len(verify_local_pair(tmp_path,manifest,IDENTITY,DELIVERY)) == 2
    for bad in (alternative+b"not padding", core, alternative.replace(b"%%EOF",b"/ByteRange [0 1 2 3]\n%%EOF")):
        with pytest.raises(ValueError):
            build_manifest(IDENTITY,DELIVERY,fixture()["listing"],canonical,bad)
    with pytest.raises(ValueError):
        build_manifest(IDENTITY,DELIVERY,fixture()["listing"],b"not the same PDF",alternative)
    with pytest.raises(ValueError):
        validate_manifest(manifest,IDENTITY,"2026-11-13")
    with pytest.raises(ValueError):
        verify_manifest_pair(manifest,alternative+b"\0",processing)
    tampered=copy.deepcopy(manifest)
    tampered["canonical_prefix_sha256"]="0"*64
    with pytest.raises(ValueError):
        validate_manifest(tampered,IDENTITY,DELIVERY)


def test_worker_reads_verified_pair_not_padded_direct_response():
    core=sample_pdf()
    raw=core+b"\0"*31167
    manifest,processing=build_manifest(IDENTITY,DELIVERY,fixture()["listing"],raw+b"meta",raw)
    class Bucket:
        async def get(self,key):
            data={manifest_key(IDENTITY):json.dumps(manifest).encode(),
                  manifest["original"]["key"]:raw,
                  manifest["processing"]["key"]:processing}.get(key)
            if data is None:
                return None
            async def read():
                return data
            return SimpleNamespace(size=len(data),arrayBuffer=read)
    url=official_urls(IDENTITY)[0]
    assert asyncio.run(read_translation_mirror(Bucket(),url,delivery=DELIVERY))==processing
    with pytest.raises(ValueError):
        asyncio.run(read_translation_mirror(Bucket(),url,delivery="2026-11-13"))
    async def fetcher(*args,**kwargs):
        return SimpleNamespace(ok=False,status=526)
    assert asyncio.run(_download_original(url,Bucket(),fetcher,delivery=DELIVERY))==processing

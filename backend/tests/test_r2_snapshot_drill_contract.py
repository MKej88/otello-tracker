from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "cloudflare" / "src" / "entry.py"
DRILL = ROOT / "cloudflare" / "src" / "snapshot_drill.py"
WRANGLER = ROOT / "cloudflare" / "wrangler.jsonc"


def test_snapshot_drill_is_exported_and_registered_without_schedule() -> None:
    entry_source = ENTRYPOINT.read_text(encoding="utf-8")
    config = json.loads(WRANGLER.read_text(encoding="utf-8"))

    assert "from snapshot_drill import R2SnapshotDrillWorkflow" in entry_source
    workflow = next(
        item for item in config["workflows"] if item["name"] == "otello-r2-snapshot-drill"
    )
    assert workflow["binding"] == "R2_SNAPSHOT_DRILL"
    assert workflow["class_name"] == "R2SnapshotDrillWorkflow"
    assert "schedules" not in workflow


def test_snapshot_drill_forces_existing_archive_path_and_only_reads_d1() -> None:
    source = DRILL.read_text(encoding="utf-8")
    tree = ast.parse(source)
    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert "R2SnapshotDrillWorkflow" in class_names
    assert "archive_d1_snapshot" in source
    assert "force=True" in source
    assert 'preflight_status="DRILL_FORCED"' in source
    assert "self.env.DB" in source
    assert "self.env.SOURCE_ARCHIVE" in source
    assert '"d1_mode": "READ_ONLY"' in source
    assert "start_job(" not in source
    assert "finish_job(" not in source
    assert "acquire_refresh_lock(" not in source

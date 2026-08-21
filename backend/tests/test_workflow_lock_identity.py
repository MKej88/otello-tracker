from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "cloudflare" / "src" / "entry.py"


def test_full_refresh_lock_owner_uses_cloudflare_instance_identity() -> None:
    source = ENTRY.read_text(encoding="utf-8")
    tree = ast.parse(source)

    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_workflow_instance_key"
    )
    helper_source = ast.get_source_segment(source, helper) or ""
    assert "instanceId" in helper_source
    assert "sha256" in helper_source
    assert "missing instanceId" in helper_source

    assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "lock_owner" for target in node.targets)
    ]
    assert len(assignments) == 1
    lock_source = ast.get_source_segment(source, assignments[0]) or ""
    assert "_workflow_instance_key(event)" in lock_source
    assert "trigger" not in lock_source

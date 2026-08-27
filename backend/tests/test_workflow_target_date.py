from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "cloudflare" / "src" / "entry.py"


def _helpers():
    source = ENTRY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"_event_value", "_nested_value", "_workflow_payload", "_workflow_target_date"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {"json": json, "datetime": datetime, "UTC": UTC, "timedelta": timedelta}
    exec(compile(module, str(ENTRY), "exec"), namespace)
    return namespace


def test_workflow_target_date_accepts_mapping_payload() -> None:
    helper = _helpers()["_workflow_target_date"]
    assert helper({"payload": {"target_date": "2026-08-26"}}) == "2026-08-26"


def test_workflow_target_date_accepts_rest_json_string_payload() -> None:
    helper = _helpers()["_workflow_target_date"]
    assert helper({"payload": '{"target_date":"2026-08-26"}'}) == "2026-08-26"


def test_workflow_target_date_accepts_params_fallback() -> None:
    helper = _helpers()["_workflow_target_date"]
    assert helper({"params": '{"target_date":"2026-08-26"}'}) == "2026-08-26"

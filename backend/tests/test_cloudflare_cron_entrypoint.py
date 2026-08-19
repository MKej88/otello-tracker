from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "cloudflare" / "src" / "entry.py"


def _scheduled_method() -> ast.AsyncFunctionDef:
    tree = ast.parse(ENTRYPOINT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Default":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "scheduled":
                    return item
    raise AssertionError("Default.scheduled mangler i Cloudflare-entrypoint")


def test_python_cron_handler_falls_back_to_worker_entrypoint_bindings() -> None:
    scheduled = _scheduled_method()
    source = ast.unparse(scheduled)

    # Cloudflare's Python runtime normally supplies env, but the production Cron
    # invocation observed 2026-08-19 supplied None. WorkerEntrypoint still exposes
    # the same bindings through self.env, which fetch() already relies on.
    assert "bindings = env if env is not None else self.env" in source
    assert "bindings.DB" in source
    assert "env.DB" not in source


def test_python_cron_handler_keeps_documented_four_parameter_signature() -> None:
    scheduled = _scheduled_method()
    assert [arg.arg for arg in scheduled.args.args] == ["self", "controller", "env", "ctx"]

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"


def _gather_call_count(path: Path, function_name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name == function_name
    )
    return sum(
        1
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
        and node.func.attr == "gather"
    )


def test_estimated_history_calculates_independent_points_concurrently() -> None:
    path = CLOUDFLARE_SRC / "estimated_nav_history.py"

    assert _gather_call_count(path, "estimated_nav_history") == 1


def test_change_attribution_fetches_independent_inputs_concurrently() -> None:
    path = CLOUDFLARE_SRC / "estimated_nav_history.py"

    assert _gather_call_count(path, "_change") == 1


def test_report_splits_are_loaded_concurrently() -> None:
    path = CLOUDFLARE_SRC / "discount_history.py"

    assert _gather_call_count(path, "_estimated_extension") == 1

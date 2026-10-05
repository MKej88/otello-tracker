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
    assert [arg.arg for arg in scheduled.args.args] == [
        "self",
        "controller",
        "env",
        "ctx",
    ]


def _run_handler(cron: str, *, fallback_env: bool = False):
    import asyncio
    import sys
    import types
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, Mock, patch

    scheduled = _scheduled_method()
    namespace = {"datetime": datetime, "UTC": UTC}
    exec(
        compile(ast.Module(body=[scheduled], type_ignores=[]), str(ENTRYPOINT), "exec"),
        namespace,
    )
    events = []

    async def fast(*args, **kwargs):
        events.append("fast")
        return {"status": "SUCCESS"}

    async def nightly(*args, **kwargs):
        events.append("nightly")
        return {"status": "STARTED"}

    async def reference(*args, **kwargs):
        events.append("reference")
        return {"status": "ok"}

    nightly_mock = AsyncMock(side_effect=nightly)
    bindings = types.SimpleNamespace(
        DB=object(), FULL_REFRESH=object(), SOURCE_ARCHIVE=object()
    )
    controller = types.SimpleNamespace(cron=cron, scheduledTime=1790654400000)
    modules = {
        "bemobi_after_oslo": types.SimpleNamespace(
            REFERENCE_CRONS=("40-42 14,15 * * 1-5", "20-22 11,12 * * 1-5"),
            run_reference_capture=AsyncMock(side_effect=reference),
        ),
        "scheduled": types.SimpleNamespace(run_scheduled=AsyncMock(side_effect=fast)),
        "nightly_trigger": types.SimpleNamespace(
            FULL_REFRESH_CRON="35 3 * * *",
            FAST_REFRESH_CRON="*/30 * * * *",
            ensure_nightly_refresh=nightly_mock,
        ),
        "repository": types.SimpleNamespace(
            D1Repository=Mock(return_value="repository")
        ),
    }
    with patch.dict(sys.modules, modules):
        result = asyncio.run(
            namespace["scheduled"](
                types.SimpleNamespace(env=bindings),
                controller,
                None if fallback_env else bindings,
                None,
            )
        )
    return result, events, nightly_mock, bindings


def test_daily_cron_starts_workflow_without_fast_refresh() -> None:
    result, events, nightly, bindings = _run_handler("35 3 * * *", fallback_env=True)
    assert result["status"] == "STARTED"
    assert events == ["nightly"]
    assert nightly.call_args.args == ("repository", bindings.FULL_REFRESH)


def test_half_hour_cron_checks_recovery_after_fast_refresh() -> None:
    result, events, _, _ = _run_handler("*/30 * * * *")
    assert events == ["fast", "nightly"]
    assert result["nightly_trigger"]["status"] == "STARTED"


def test_unknown_cron_does_not_start_nightly_workflow() -> None:
    _, _, nightly, _ = _run_handler("0 1 * * *")
    nightly.assert_not_awaited()


def test_reference_cron_runs_only_bounded_capture() -> None:
    result, events, nightly, _ = _run_handler("40-42 14,15 * * 1-5", fallback_env=True)
    assert result["status"] == "ok"
    assert events == ["reference"]
    nightly.assert_not_awaited()

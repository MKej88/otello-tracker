from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cloudflare/src'))
from nightly_trigger import completed_nightly_job  # noqa: E402


def workflow_run():
    # Execute the real orchestration without importing the Cloudflare-only entrypoint.
    tree = ast.parse((ROOT / 'cloudflare/src/entry.py').read_text())
    workflow = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FullRefreshWorkflow')
    run = next(n for n in workflow.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'run')

    class WithoutImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            return None

    module = ast.fix_missing_locations(WithoutImports().visit(ast.Module(body=[run], type_ignores=[])))
    namespace = {
        '_workflow_trigger': lambda e: e['trigger'],
        '_workflow_target_date': lambda e: e['target_date'],
        '_workflow_instance_key': lambda e: 'second-instance',
        'FULL_REFRESH_LOCK_TTL_SECONDS': 10800,
        'PerformanceD1WriteRepository': lambda db: db,
        'acquire_refresh_lock': AsyncMock(return_value={'acquired': True, 'token': 'lease'}),
        'release_refresh_lock': AsyncMock(return_value=True),
        'completed_nightly_job': AsyncMock(return_value={'id': 42}),
        'start_full_refresh': AsyncMock(),
        'send_full_refresh_status_email': AsyncMock(),
    }
    exec(compile(module, '<workflow>', 'exec'), namespace)
    return namespace


class Step:
    def __init__(self):
        self.calls = []

    def do(self, name, config):
        self.calls.append(name)
        return lambda fn: fn


def test_legacy_schedule_exits_before_lock_writes_and_email():
    ns = workflow_run()
    result = asyncio.run(ns['run'](None, {'trigger': 'workflow_schedule:35 3 * * *', 'target_date': '2026-10-16'}, Step()))
    assert result['reason'] == 'legacy_schedule_disabled'
    ns['acquire_refresh_lock'].assert_not_awaited()
    ns['start_full_refresh'].assert_not_awaited()
    ns['send_full_refresh_status_email'].assert_not_awaited()


def test_completed_job_after_wait_releases_lock_without_second_run_or_mail():
    ns = workflow_run()
    step = Step()
    result = asyncio.run(ns['run'](SimpleNamespace(env=SimpleNamespace(DB=object())), {
        'trigger': 'worker_cron:35 3 * * *', 'target_date': '2026-10-16',
    }, step))
    assert result['reason'] == 'already_completed'
    assert result['existing_job_id'] == 42
    assert step.calls.index('acquire full refresh writer lock') < step.calls.index('check completed nightly refresh after writer lock')
    ns['release_refresh_lock'].assert_awaited_once()
    ns['start_full_refresh'].assert_not_awaited()
    ns['send_full_refresh_status_email'].assert_not_awaited()


def test_manual_reruns_remain_possible():
    repo = SimpleNamespace(first=AsyncMock(return_value={'id': 42}))
    assert asyncio.run(completed_nightly_job(repo, target_date='2026-10-16', trigger='workflow_manual')) is None
    repo.first.assert_not_awaited()


def test_guard_matches_only_success_for_target_date():
    import sqlite3
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE job_runs (id INTEGER PRIMARY KEY, job_name TEXT, status TEXT, metadata_json TEXT)')

    async def first(sql, args):
        row = db.execute(sql, args).fetchone()
        return dict(row) if row else None

    repo = SimpleNamespace(first=first)
    for status, metadata in [('PARTIAL', '{"target_date":"2026-10-16"}'), ('FAILED', '{"target_date":"2026-10-16"}'), ('SUCCESS', '{"target_date":"2026-10-15"}'), ('SUCCESS', 'invalid')]:
        db.execute('INSERT INTO job_runs(job_name,status,metadata_json) VALUES (?,?,?)', ('cloudflare_full_refresh', status, metadata))
    assert asyncio.run(completed_nightly_job(repo, target_date='2026-10-16', trigger='worker_cron:35 3 * * *')) is None
    db.execute('INSERT INTO job_runs(job_name,status,metadata_json) VALUES (?,?,?)', ('cloudflare_full_refresh', 'SUCCESS', '{"target_date":"2026-10-16"}'))
    assert asyncio.run(completed_nightly_job(repo, target_date='2026-10-16', trigger='worker_cron:35 3 * * *')) == {'id': 5}
    db.close()

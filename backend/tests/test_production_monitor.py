from __future__ import annotations

import copy
import json
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cloudflare/src'))
from production_monitor import (  # noqa: E402
    REQUIRED_SOURCES, assess_production, expected_nightly_date,
    monitoring_queries, render_monitoring,
)

NOW = datetime(2026, 10, 17, 4, 30, tzinfo=UTC)


def fixture():
    return dict(now=NOW,
        jobs=[dict(id=1, started_at='2026-10-17T03:35:00Z', finished_at='2026-10-17T03:39:00Z',
                   status='SUCCESS', metadata_json=json.dumps({'target_date': '2026-10-16'}))],
        sources=[dict(code=code, status='OK', checked_at='2026-10-17T03:39:00Z') for code in REQUIRED_SOURCES],
        prices=[dict(symbol=s, data_date='2026-10-16') for s in ['OTEC', 'BMOB3', 'LIF']],
        states=[dict(key=key, updated_at='2026-10-17T03:39:00Z', value=json.dumps({
            'checked_date': '2026-10-16', 'data_date': '2026-10-16', 'rows': []}))
            for key in ['bemobi_official_news_v1', 'cvm_ipe_archive_freshness']])


def failures(data):
    return [r['name'] for r in assess_production(**data)['checks'] if not r['ok']]


def test_healthy_data_and_no_new_notices_are_ok():
    assert not assess_production(**fixture())['unhealthy']


def test_missing_job_and_wrong_target_are_detected():
    data = fixture()
    data['jobs'][0]['metadata_json'] = '{"target_date":"2026-10-15"}'
    assert 'Nattkjøring ferdig' in failures(data)
    data['jobs'] = []
    assert 'Nattkjøring ferdig' in failures(data)


def test_duplicate_success_detected_but_failed_attempt_then_recovery_allowed():
    data = fixture()
    data['jobs'].append(copy.deepcopy(data['jobs'][0]))
    assert 'Ingen dobbel nattkjøring' in failures(data)
    data['jobs'][0]['status'] = 'FAILED'
    assert 'Ingen dobbel nattkjøring' not in failures(data)


def test_running_or_partial_is_not_a_successful_night():
    for status in ['RUNNING', 'PARTIAL', 'FAILED']:
        data = fixture()
        data['jobs'][0]['status'] = status
        assert 'Nattkjøring ferdig' in failures(data)


def test_deadline_grace_and_calendar_target_across_year_boundary():
    assert expected_nightly_date(NOW.replace(hour=4, minute=29)) == date(2026, 10, 15)
    assert expected_nightly_date(NOW) == date(2026, 10, 16)
    assert expected_nightly_date(datetime(2027, 1, 1, 4, 30, tzinfo=UTC)) == date(2026, 12, 31)


def test_ok_health_cannot_hide_stale_prices_or_stale_polling():
    data = fixture()
    data['prices'][0]['data_date'] = '2026-10-14'
    data['sources'][0]['checked_at'] = '2026-10-14T03:39:00Z'
    assert {'Sluttkurs: OTEC', 'Kildekontakt: NORGES_BANK'} <= set(failures(data))


def test_market_weekend_and_distinct_brazilian_holiday():
    data = fixture()
    data['now'] = datetime(2026, 10, 13, 4, 30, tzinfo=UTC)
    data['prices'] = [dict(symbol='OTEC', data_date='2026-10-12'),
                      dict(symbol='BMOB3', data_date='2026-10-09'), dict(symbol='LIF', data_date='2026-10-09')]
    assert 'Sluttkurs: BMOB3' not in failures(data)  # B3 closed October 12.
    assert 'Sluttkurs: OTEC' not in failures(data)
    data['now'] = datetime(2026, 10, 19, 4, 30, tzinfo=UTC)
    data['prices'] = [dict(symbol=s, data_date='2026-10-16') for s in ['OTEC', 'BMOB3', 'LIF']]
    assert not any(name.startswith('Sluttkurs') for name in failures(data))


def test_missing_down_and_future_source_checks_are_detected():
    data = fixture()
    data['sources'] = data['sources'][1:]
    assert 'Kildekontakt: NORGES_BANK' in failures(data)
    data = fixture()
    data['sources'][0]['status'] = 'DOWN'
    assert 'Kildekontakt: NORGES_BANK' in failures(data)
    data['sources'][0].update(status='OK', checked_at='2026-10-18T03:39:00Z')
    assert 'Kildekontakt: NORGES_BANK' in failures(data)


def test_news_archive_age_separate_from_successful_contact():
    data = fixture()
    data['states'][1]['value'] = '{"checked_date":"2026-10-16","data_date":"2026-10-09"}'
    assert 'CVM-filens datadato' in failures(data)
    assert 'Nyhetskilde sjekket: CVM' not in failures(data)
    data['states'][0]['value'] = 'invalid'
    assert 'Nyhetskilde sjekket: Bemobi IR' in failures(data)


def test_missing_and_future_prices_fail_and_lif_uses_existing_seven_day_limit():
    data = fixture()
    data['prices'] = [dict(symbol='LIF', data_date='2026-10-08'), dict(symbol='BMOB3', data_date='2026-10-18')]
    assert {'Sluttkurs: OTEC', 'Sluttkurs: BMOB3', 'Sluttkurs: LIF'} <= set(failures(data))


def test_queries_execute_read_only_and_bound_historical_window():
    db = sqlite3.connect(':memory:')
    db.executescript('''CREATE TABLE job_runs(id INTEGER, job_name TEXT, started_at TEXT, finished_at TEXT, status TEXT, metadata_json TEXT);
    CREATE TABLE market_prices(instrument_id INTEGER, trading_date TEXT, price_type TEXT);
    CREATE TABLE instruments(id INTEGER, symbol TEXT);
    CREATE TABLE runtime_state(key TEXT, value TEXT, updated_at TEXT);''')
    db.execute('PRAGMA query_only=ON')
    for query in monitoring_queries(NOW):
        assert db.execute(query['sql'], query.get('params', [])).fetchall() == []
    db.close()


def test_report_uses_oslo_time_and_excludes_raw_errors_and_metadata():
    data = fixture()
    data['jobs'][0]['metadata_json'] = '{"target_date":"2026-10-16","secret":"do-not-log"}'
    data['sources'][0]['error_message'] = 'do-not-log'
    rendered = render_monitoring(assess_production(**data))
    assert '17.10.2026 05:35 +0200' in rendered
    assert 'do-not-log' not in rendered
    assert 'AVVIK' not in rendered


def test_workflow_query_pack_and_report_integration(tmp_path, monkeypatch):
    import re
    import textwrap
    workflow = (ROOT / '.github/workflows/cloudflare-workflow-diagnostics.yml').read_text()
    scripts = [textwrap.dedent(s) for s in re.findall(r"          python - <<'PY'\n(.*?)\n          PY", workflow, re.S)]
    for script in scripts:
        compile(script, '<diagnostics>', 'exec')
    pack_script = next(s for s in scripts if 'job_columns =' in s)
    report_script = next(s for s in scripts if 'monitoring = assess_production(' in s)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('D1_DATABASE_NAME', 'test')
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(tmp_path / 'summary'))
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'output'))
    exec(compile(pack_script, '<query-pack>', 'exec'), {})
    batch = json.loads((tmp_path / 'd1-query-request.json').read_text())['batch']
    assert len(batch) == 9
    assert all(q['sql'].strip().upper().startswith('SELECT ') for q in batch)
    data = fixture()
    rows = [[data['jobs'][0]], [dict(status='SUCCESS', started_at='2026-10-17T04:00:00Z', finished_at='2026-10-17T04:01:00Z')],
            [], data['sources'], [dict(base_currency=c, observed_date='2026-10-16') for c in ['BRL', 'USD']],
            [], data['jobs'], data['prices'], data['states']]
    (tmp_path / 'd1-query.json').write_text(json.dumps(dict(success=True, result=[dict(success=True, results=r) for r in rows])))
    report_script = report_script.replace('now = datetime.now(UTC)', 'now = datetime(2026, 10, 17, 4, 30, tzinfo=UTC)')
    exec(compile(report_script, '<report>', 'exec'), {})
    assert 'd1_unhealthy=false' in (tmp_path / 'output').read_text()
    rows[6].append(copy.deepcopy(data['jobs'][0]))
    (tmp_path / 'd1-query.json').write_text(json.dumps(dict(success=True, result=[dict(success=True, results=r) for r in rows])))
    exec(compile(report_script, '<report>', 'exec'), {})
    assert (tmp_path / 'output').read_text().endswith('d1_unhealthy=true\n')
    assert 'Ingen dobbel nattkjøring | AVVIK' in (tmp_path / 'summary').read_text()

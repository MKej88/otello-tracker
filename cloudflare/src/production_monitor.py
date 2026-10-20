"""Read-only production checks used by GitHub Actions, independent of Worker bindings."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from b3_calendar import is_b3_trading_day
from nightly_trigger import nightly_due_at
from oslo_calendar import is_oslo_bors_trading_day

REQUIRED_SOURCES = ('NORGES_BANK', 'YAHOO_FINANCE', 'B3', 'CVM', 'BEMOBI_IR', 'NEWSWEB', 'EURONEXT')
MAX_SOURCE_AGE = timedelta(hours=36)
# PR 783 added these observations after the October 17 overnight run.
NEWS_FRESHNESS_FIRST_TARGET = date(2026, 10, 17)
# Closed incident: PR 784 removed the native schedule and verified the deployment.
# Match the exact two observed runs; a third/new run must still alert.
CLOSED_DUPLICATE_RUNS = {
    '2026-10-16': frozenset({
        ('2026-10-17T03:36:00.356Z', '2026-10-17T03:38:59.833Z'),
        ('2026-10-17T03:43:04.680Z', '2026-10-17T03:46:36.876Z'),
    }),
}


def monitoring_queries(now: datetime) -> list[dict]:
    return [
        {'sql': """SELECT id, started_at, finished_at, status, metadata_json
                   FROM job_runs WHERE job_name='cloudflare_full_refresh'
                   AND started_at >= ? ORDER BY id DESC LIMIT 512""",
         'params': [(now.astimezone(UTC) - timedelta(days=8)).isoformat()]},
        {'sql': """SELECT i.symbol, MAX(mp.trading_date) AS data_date
                   FROM market_prices mp JOIN instruments i ON i.id=mp.instrument_id
                   JOIN sources s ON s.id=mp.source_id
                   WHERE (i.symbol IN ('OTEC','BMOB3','LIF') AND mp.price_type='CLOSE')
                      OR (i.symbol='OTEC' AND s.code='EURONEXT' AND mp.price_type='LAST'
                          AND json_valid(mp.metadata_json)
                          AND json_extract(mp.metadata_json,'$.feed_mode') IN
                              ('EOD_LAST_TRADE','WORKFLOW_R2_RECOVERY'))
                   GROUP BY i.symbol"""},
        {'sql': """SELECT key, value, updated_at FROM runtime_state
                   WHERE key IN ('bemobi_official_news_v1','cvm_ipe_archive_freshness')"""},
    ]


def _json(raw) -> dict:
    try:
        value = json.loads(raw or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _date(raw) -> date | None:
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def _time(raw) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        return value.astimezone(UTC) if value.tzinfo else None
    except ValueError:
        return None


def expected_nightly_date(now: datetime) -> date:
    due = nightly_due_at(now)
    if now.astimezone(UTC) < due + timedelta(minutes=55):
        due -= timedelta(days=1)
    return due.date() - timedelta(days=1)


def _last_session(day: date, is_session) -> date:
    while not is_session(day):
        day -= timedelta(days=1)
    return day


def assess_production(*, now: datetime, jobs: list[dict], sources: list[dict],
                      prices: list[dict], states: list[dict],
                      allow_secondary_bemobi_warning: bool = False) -> dict:
    now = now.astimezone(UTC)
    target = expected_nightly_date(now)
    checks = []

    def add(name, ok, actual, expected, state=None):
        checks.append({'name': name, 'ok': bool(ok), 'actual': str(actual),
                       'expected': str(expected), 'state': state or ('OK' if ok else 'AVVIK')})

    target_jobs = [r for r in jobs if _json(r.get('metadata_json')).get('target_date') == target.isoformat()]
    successful = [r for r in target_jobs if r.get('status') == 'SUCCESS']
    secondary_partial = (allow_secondary_bemobi_warning and not successful
                         and len(target_jobs) == 1
                         and target_jobs[0].get('status') == 'PARTIAL')
    add('Nattkjøring ferdig', bool(successful),
        f'{len(successful)} vellykkede, {len(target_jobs)} forsøk', f'datadato {target}',
        state='ADVARSEL' if secondary_partial else None)
    # Count actual database jobs, not harmless SKIPPED Workflow instances.
    closed_runs = CLOSED_DUPLICATE_RUNS.get(target.isoformat())
    observed_runs = frozenset((r.get('started_at'), r.get('finished_at')) for r in successful)
    closed_incident = bool(closed_runs and len(target_jobs) == len(closed_runs) and len(successful) == len(closed_runs) and observed_runs == closed_runs)
    if closed_incident:
        add('Ingen dobbel nattkjøring', True, '2 kjøringer fra avsluttet hendelse; rettet i PR 784',
            'nye dobbeltkjøringer varsles fortsatt', state='HISTORISK')
    else:
        add('Ingen dobbel nattkjøring', len(successful) <= 1, f'{len(successful)} vellykkede, {len(target_jobs)} forsøk totalt', 'maksimalt 1 vellykket; manuelle omkjøringer må vurderes')

    by_source = {r.get('code'): r for r in sources}
    for code in REQUIRED_SOURCES:
        row = by_source.get(code, {})
        checked = _time(row.get('checked_at'))
        age_ok = checked is not None and -timedelta(minutes=5) <= now - checked <= MAX_SOURCE_AGE
        source_ok = row.get('status') == 'OK' and age_ok
        source_warning = (allow_secondary_bemobi_warning and code == 'BEMOBI_IR'
                          and row.get('status') == 'DEGRADED' and age_ok)
        add(f'Kildekontakt: {code}', source_ok,
            f"{row.get('status', 'MANGLER')}, sist sjekket {oslo_time(row.get('checked_at'))}",
            'OK og kontrollert siste 36 timer',
            state='ADVARSEL' if source_warning else None)

    by_symbol = {r.get('symbol'): _date(r.get('data_date')) for r in prices}
    # Use the most recently due overnight date; intraday data is not expected here.
    for symbol, calendar in [('OTEC', is_oslo_bors_trading_day), ('BMOB3', is_b3_trading_day)]:
        expected = _last_session(target, calendar)
        actual = by_symbol.get(symbol)
        label = 'Kurs ved dagsavslutning: OTEC' if symbol == 'OTEC' else f'Sluttkurs: {symbol}'
        add(label, actual is not None and expected <= actual <= now.date(), actual or 'MANGLER', f'minst {expected} (børskalender)')
    # Retain the existing Life360 freshness tolerance; do not invent a US holiday calendar.
    lif = by_symbol.get('LIF')
    add('Sluttkurs: LIF', lif is not None and target - timedelta(days=7) <= lif <= now.date(), lif or 'MANGLER', f'høyst 7 kalenderdager før {target}')

    by_key = {r.get('key'): r for r in states}
    for key, label in [('bemobi_official_news_v1', 'Bemobi IR'), ('cvm_ipe_archive_freshness', 'CVM')]:
        row = by_key.get(key, {})
        if not row and target < NEWS_FRESHNESS_FIRST_TARGET:
            deadline = '18.10.2026 06:30 norsk tid (første frist etter innføring)'
            add(f'Nyhetskilde sjekket: {label}', True, 'avventer første nattkjøring med nye ferskhetsfelter',
                deadline, state='AVVENTER')
            if label == 'CVM':
                add('CVM-filens datadato', True, 'ennå ikke registrert', deadline, state='AVVENTER')
            continue
        data = _json(row.get('value'))
        checked = _date(data.get('checked_date'))
        updated = _time(row.get('updated_at'))
        fresh_read = updated is not None and -timedelta(minutes=5) <= now - updated <= MAX_SOURCE_AGE
        add(f'Nyhetskilde sjekket: {label}', checked is not None and target <= checked <= now.date() and fresh_read,
            checked or 'MANGLER', f'minst datadato {target}, lagret siste 36 timer')
        if label == 'CVM':
            archive_date = _date(data.get('data_date'))
            add('CVM-filens datadato', archive_date is not None and target - timedelta(days=3) <= archive_date <= now.date(),
                archive_date or 'MANGLER', f'høyst 3 kalenderdager før {target}')

    # A controlled warning is still an observation, but no longer a fatal AVVIK.
    return {'target_date': target.isoformat(),
            'unhealthy': any(c['state'] == 'AVVIK' for c in checks),
            'warnings': [c for c in checks if c['state'] == 'ADVARSEL'],
            'checks': checks, 'jobs': jobs}


def oslo_time(raw) -> str:
    parsed = _time(raw)
    return parsed.astimezone(ZoneInfo('Europe/Oslo')).strftime('%d.%m.%Y %H:%M %z') if parsed else '-'


def render_monitoring(report: dict) -> str:
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')

    lines = ['', '## Nattkjøring og ferskhet', '',
             f"- Kontrollert datadato: `{report['target_date']}`",
             '- Tidspunkter nedenfor vises i Europe/Oslo.', '',
             '| Kontroll | Resultat | Faktisk | Forventet |', '|---|---|---|---|']
    for c in report['checks']:
        lines.append(f"| {cell(c['name'])} | {cell(c['state'])} | {cell(c['actual'])} | {cell(c['expected'])} |")
    lines += ['', '### Fullkjøringer siste åtte døgn', '',
              '| Start (norsk tid) | Slutt (norsk tid) | Status | Datadato |', '|---|---|---|---|']
    for row in report['jobs']:
        target = _date(_json(row.get('metadata_json')).get('target_date'))
        status = row.get('status') if row.get('status') in {'SUCCESS', 'PARTIAL', 'FAILED', 'RUNNING'} else 'UKJENT'
        lines.append(f"| {oslo_time(row.get('started_at'))} | {oslo_time(row.get('finished_at'))} | {status} | {target or '-'} |")
    return '\n'.join(lines) + '\n'

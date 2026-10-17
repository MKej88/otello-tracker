from __future__ import annotations

import copy
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cloudflare/src'))
from nav_cache_audit import audit_contract, audit_queries, assess_nav_cache, render_audit  # noqa: E402


def audit_fixture():
    now = datetime(2026, 10, 17, 4, 30, tzinfo=UTC)
    core_components = dict(bmob3=dict(price_id=1, brl_nok_id=2, holding_id=7), otec=dict(share_count_id=8, price_id=4), cash=dict(daily_cash_id=3))
    core = dict(id=1, nav_scope='CORE', calculation_version='core-market-nav-daily-v1', as_of_at='2026-10-16T00:00:00Z',
                nav_total_nok='500', nav_per_share_nok='5', shares_outstanding=100, bemobi_value_nok='400',
                cash_estimate_nok='100', other_net_assets_nok='0', otec_price_nok='4', discount_pct='20',
                components_json=json.dumps(core_components), updated_at='2026-10-17T04:20:00Z',
                input_price_brl='10', input_holding_shares=20, input_brl_nok='2', input_fx_base='BRL', input_fx_quote='NOK',
                input_otec_price='4', input_price_date='2026-10-16', input_fx_at='2026-10-16T00:00:00Z', input_cash_nok='100', input_outstanding=100,
                expected_holding_id=7, expected_share_count_id=8, expected_price_date='2026-10-16', expected_fx_date='2026-10-16')
    full = dict(core, id=2, nav_scope='FULL', calculation_version='full-market-nav-daily-v2', nav_total_nok='550',
                nav_per_share_nok='5.5', other_net_assets_nok='50', input_ona_nok='50', discount_pct=str((1-4/5.5)*100),
                components_json=json.dumps(dict(other_net_assets=dict(option_liability=dict(amount_nok='10', inputs=dict(option_count=10, strike_nok='2'))))))
    nav = (560 + 10*2)/110
    total = nav*100
    economic = dict(ready=True, as_of_date='2026-10-16', nav_per_share=nav, nav_total_mnok=total/1000000,
                    shares_outstanding=100, discount_pct=(1-4/nav)*100, conservative_nav_per_share=nav,
                    composition=[dict(key='all', amount_mnok=total/1000000, per_share_nok=nav)], option={},
                    cash_fx=dict(adjustment_mnok=0), operating_costs=dict(base_mnok=0, conservative_mnok=0),
                    life360=dict(ready=True, shares=2, price=3, fx_rate=4, market_value_nok=24, adjustment_nok=0))
    snapshot = dict(version=audit_contract()['version'], generated_at='2026-10-17T04:25:00Z',
                    summary=dict(ready=True, as_of_date='2026-10-16', nav_per_share=5.5, shares_outstanding=100, otec_price=4, nav_discount_pct=(1-4/5.5)*100, bemobi_value_mnok=.0004, estimated_cash_mnok=.0001, other_net_assets_mnok=.00005, bemobi_shares=20),
                    economic=economic, quotes=dict(symbols=dict(OTEC=dict(last=4))), buyback={}, events={})
    public = copy.deepcopy(snapshot)
    public['meta'] = dict(snapshot_version=snapshot['version'], generated_at=snapshot['generated_at'], source='hot_snapshot')
    return dict(now=now, contract=audit_contract(), nav_rows=[core, full], cache_rows=[dict(value=json.dumps(snapshot))], lock_rows=[], public=public)


def failures(data):
    return [r['name'] for r in assess_nav_cache(**data)['checks'] if not r['ok']]


def edit_cache(data, edit):
    payload = json.loads(data['cache_rows'][0]['value'])
    edit(payload)
    data['cache_rows'][0]['value'] = json.dumps(payload)


def test_independent_accounting_and_investor_models_reconcile():
    assert not assess_nav_cache(**audit_fixture())['unhealthy']


def test_database_arithmetic_and_raw_input_changes_are_detected():
    data = audit_fixture()
    data['nav_rows'][0]['nav_per_share_nok'] = '6'
    assert 'CORE: NAV per aksje' in failures(data)
    data = audit_fixture()
    data['nav_rows'][0]['input_holding_shares'] = 21
    assert 'Bemobi: aksjer × kurs × BRL/NOK' in failures(data)
    data['nav_rows'][0]['expected_holding_id'] = 99
    assert 'CORE: siste gyldige beholdning' in failures(data)
    data['nav_rows'][0]['expected_fx_date'] = '2026-10-17'
    assert 'CORE: valutadato mot grunnlag' in failures(data)


def test_stale_or_wrong_cache_contract_is_detected():
    for edit, name in [(lambda c: c.update(version=0), 'Cache: versjon'),
                       (lambda c: c.update(generated_at='2026-10-16T00:00:00Z'), 'Cache: alder'),
                       (lambda c: c.update(generated_at='2026-10-18T00:00:00Z'), 'Cache: alder'),
                       (lambda c: c.pop('events'), 'Cache: alle seksjoner')]:
        data = audit_fixture()
        edit_cache(data, edit)
        assert name in failures(data)


def test_public_page_stale_even_when_database_cache_is_fresh():
    data = audit_fixture()
    data['public']['meta']['generated_at'] = '2026-10-16T00:00:00Z'
    assert {'Nettsiden: dataenes alder', 'Nettsiden: samme cachegenerasjon'} <= set(failures(data))
    data['public']['summary']['nav_per_share'] = 4
    assert 'Nettsiden: regnskaps-NAV mot D1' in failures(data)


def test_recent_concurrent_rebuild_is_pending_but_stale_public_data_still_fails():
    data = audit_fixture()
    edit_cache(data, lambda c: c.update(generated_at='2026-10-17T04:29:30Z'))
    report = assess_nav_cache(**data)
    check = next(r for r in report['checks'] if r['name'] == 'Nettsiden: samme cachegenerasjon')
    assert check['state'] == 'AVVENTER'
    data['public']['meta']['generated_at'] = '2026-10-16T00:00:00Z'
    assert 'Nettsiden: dataenes alder' in failures(data)


def test_cache_must_follow_new_nav_after_short_rebuild_grace():
    data = audit_fixture()
    for row in data['nav_rows']:
        row['updated_at'] = '2026-10-17T04:26:00Z'
    assert 'Cache: beregnet etter siste NAV-endring' in failures(data)
    for row in data['nav_rows']:
        row['updated_at'] = '2026-10-17T04:29:30Z'
    check = next(c for c in assess_nav_cache(**data)['checks'] if c['name'] == 'Cache: beregnet etter siste NAV-endring')
    assert check['state'] == 'AVVENTER'


def test_active_writer_defers_cross_row_comparison_only():
    data = audit_fixture()
    data['lock_rows'] = [dict(value='full:test|2026-10-17T05:00:00Z', updated_at='2026-10-17T04:29:30Z')]
    data['nav_rows'][0]['input_cash_nok'] = '200'
    assert 'CORE: cash mot grunnlagsrad' not in failures(data)
    data['nav_rows'][0]['nav_per_share_nok'] = '8'
    assert 'CORE: NAV per aksje' in failures(data)
    data['lock_rows'][0]['value'] = 'full:test|2026-10-17T04:00:00Z'
    assert 'CORE: cash mot grunnlagsrad' in failures(data)


def test_investor_option_formula_compares_to_accounting_database():
    data = audit_fixture()
    data['public']['economic']['nav_per_share'] += 1
    assert 'Nettsiden: investor-NAV etter opsjonsoppgjør' in failures(data)
    data = audit_fixture()
    data['public']['economic']['composition'][0]['amount_mnok'] += .001
    assert 'Nettsiden: investor-NAV summerer' in failures(data)
    data = audit_fixture()
    data['public']['economic']['life360']['market_value_nok'] = 25.1
    assert 'Nettsiden: Life360 aksjer × kurs × USD/NOK' in failures(data)


def test_missing_corrupt_and_non_finite_numbers_fail_without_crash():
    for value in [0, -1, 'NaN', 'Infinity', None, 'bad']:
        data = audit_fixture()
        data['nav_rows'][0]['shares_outstanding'] = value
        assert 'CORE: gyldige NAV-tall' in failures(data)
    data = audit_fixture()
    data['cache_rows'] = [dict(value='invalid')]
    data['public'] = {}
    assert assess_nav_cache(**data)['unhealthy']
    data = audit_fixture()
    data['nav_rows'] = []
    assert 'NAV-grunnlag' in failures(data)


def test_public_quote_discount_and_fallback_are_checked():
    data = audit_fixture()
    data['public']['economic']['discount_pct'] = 0
    data['public']['meta']['source'] = 'live_fallback'
    assert {'Nettsiden: investor-NAV-rabatt', 'Nettsiden: bruker lagret cache'} <= set(failures(data))


def test_queries_join_real_input_rows_and_are_read_only():
    data = audit_fixture()
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''CREATE TABLE nav_snapshots(id INTEGER, nav_scope TEXT, calculation_version TEXT, as_of_at TEXT,
      components_json TEXT); CREATE TABLE market_prices(id INTEGER,instrument_id INTEGER,price TEXT,trading_date TEXT,price_type TEXT);
      CREATE TABLE fx_rates(id INTEGER,rate TEXT,base_currency TEXT,quote_currency TEXT,observed_at TEXT);
      CREATE TABLE bemobi_holdings(id INTEGER, shares INTEGER,effective_from TEXT,effective_to TEXT);
      CREATE TABLE otello_share_counts(id INTEGER,outstanding_shares INTEGER,effective_from TEXT);
      CREATE TABLE cash_daily_estimates(id INTEGER,cash_nok TEXT);
      CREATE TABLE other_net_assets_daily_estimates(estimate_date TEXT, amount_nok TEXT);
      CREATE TABLE instruments(id INTEGER,symbol TEXT); CREATE TABLE runtime_state(key TEXT,value TEXT,updated_at TEXT);
      INSERT INTO instruments VALUES(1,'BMOB3'); INSERT INTO instruments VALUES(2,'OTEC');
      INSERT INTO market_prices VALUES(4,2,'4','2026-10-16','LAST'); INSERT INTO market_prices VALUES(1,1,'10','2026-10-16','CLOSE');
      INSERT INTO fx_rates VALUES(2,'2','BRL','NOK','2026-10-16T00:00:00Z');
      INSERT INTO bemobi_holdings VALUES(7,20,'2026-01-01',NULL);
      INSERT INTO otello_share_counts VALUES(8,100,'2026-01-01');
      INSERT INTO cash_daily_estimates VALUES(3,'100');
      INSERT INTO other_net_assets_daily_estimates VALUES('2026-10-16','50');''')
    for row in data['nav_rows']:
        db.execute('INSERT INTO nav_snapshots VALUES(?,?,?,?,?)', tuple(row[k] for k in ['id','nav_scope','calculation_version','as_of_at','components_json']))
    db.execute('PRAGMA query_only=ON')
    results = [db.execute(q['sql'], q['params']).fetchall() for q in audit_queries(data['contract'])]
    assert len(results[0]) == 2
    core = next(dict(r) for r in results[0] if r['nav_scope'] == 'CORE')
    assert core['input_holding_shares'] == 20 and core['input_brl_nok'] == '2'
    assert core['expected_holding_id'] == 7 and core['expected_price_date'] == '2026-10-16'
    db.close()


def test_contract_is_loaded_without_worker_imports_and_report_has_no_raw_data():
    data = audit_fixture()
    data['cache_rows'][0]['secret'] = 'must-not-print'
    report = render_audit(assess_nav_cache(**data))
    assert 'must-not-print' not in report
    assert audit_contract()['version'] == data['contract']['version']
    assert 'NAV-avstemming og cache' in report

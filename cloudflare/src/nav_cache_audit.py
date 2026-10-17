"""Independent, read-only NAV arithmetic and first-screen cache reconciliation."""
from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

MILLION = Decimal('1000000')
MONEY_TOLERANCE = Decimal('1')  # NOK; permits decimal-to-JSON float conversion.
PER_SHARE_TOLERANCE = Decimal('0.000001')


def audit_contract(root: Path | None = None) -> dict:
    """Read literal production contracts without importing FastAPI or Worker bindings."""
    root = root or Path(__file__).resolve().parents[2]
    def literal(node):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            left, right = literal(node.left), literal(node.right)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left * right
            raise ValueError('non-numeric contract expression')
        return ast.literal_eval(node)
    def constants(name):
        result = {}
        tree = ast.parse((root / 'cloudflare/src' / name).read_text())
        for node in tree.body:
            if isinstance(node, ast.Assign):
                try:
                    value = literal(node.value)
                except (ValueError, TypeError):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        result[target.id] = value
        return result
    cache = constants('dashboard_hot_snapshot.py')
    nav = constants('nav_refresh.py')
    return dict(key=cache['STATE_KEY'], version=cache['SNAPSHOT_VERSION'],
                max_age=cache['SNAPSHOT_MAX_AGE_SECONDS'], components=cache['_COMPONENTS'],
                core_version=nav['CORE_CALCULATION_VERSION'], full_version=nav['FULL_CALCULATION_VERSION'])


def audit_queries(contract: dict) -> list[dict]:
    return [dict(sql="""WITH latest AS (
        SELECT as_of_at FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope='FULL'
        ORDER BY as_of_at DESC, id DESC LIMIT 1
    ), selected AS (
        SELECT n.*, CASE WHEN json_valid(n.components_json) THEN n.components_json ELSE '{}' END AS inputs
        FROM nav_snapshots n JOIN latest l ON l.as_of_at=n.as_of_at
        WHERE (n.calculation_version=? AND n.nav_scope='CORE')
           OR (n.calculation_version=? AND n.nav_scope='FULL')
    ) SELECT n.*, p.price AS input_price_brl, p.trading_date AS input_price_date,
        op.price AS input_otec_price, fx.rate AS input_brl_nok, fx.observed_at AS input_fx_at, fx.base_currency AS input_fx_base, fx.quote_currency AS input_fx_quote,
        h.shares AS input_holding_shares, sc.outstanding_shares AS input_outstanding,
        c.cash_nok AS input_cash_nok, o.amount_nok AS input_ona_nok,
        (SELECT id FROM bemobi_holdings WHERE effective_from<=substr(n.as_of_at,1,10)
          AND (effective_to IS NULL OR effective_to>=substr(n.as_of_at,1,10)) ORDER BY effective_from DESC,id DESC LIMIT 1) AS expected_holding_id,
        (SELECT id FROM otello_share_counts WHERE effective_from<=substr(n.as_of_at,1,10)
          ORDER BY effective_from DESC,id DESC LIMIT 1) AS expected_share_count_id,
        (SELECT MAX(m.trading_date) FROM market_prices m JOIN instruments i ON i.id=m.instrument_id
          WHERE i.symbol='BMOB3' AND m.price_type IN ('CLOSE','LAST') AND m.trading_date<=substr(n.as_of_at,1,10)) AS expected_price_date,
        (SELECT MAX(substr(f.observed_at,1,10)) FROM fx_rates f WHERE f.base_currency='BRL' AND f.quote_currency='NOK'
          AND substr(f.observed_at,1,10)<=substr(n.as_of_at,1,10)) AS expected_fx_date
      FROM selected n
      LEFT JOIN market_prices p ON p.id=json_extract(n.inputs,'$.bmob3.price_id')
      LEFT JOIN market_prices op ON op.id=json_extract(n.inputs,'$.otec.price_id')
      LEFT JOIN fx_rates fx ON fx.id=json_extract(n.inputs,'$.bmob3.brl_nok_id')
      LEFT JOIN bemobi_holdings h ON h.id=json_extract(n.inputs,'$.bmob3.holding_id')
      LEFT JOIN otello_share_counts sc ON sc.id=json_extract(n.inputs,'$.otec.share_count_id')
      LEFT JOIN cash_daily_estimates c ON c.id=json_extract(n.inputs,'$.cash.daily_cash_id')
      LEFT JOIN other_net_assets_daily_estimates o ON o.estimate_date=substr(n.as_of_at,1,10)
      ORDER BY n.nav_scope""", params=[contract['full_version'], contract['core_version'], contract['full_version']]),
        dict(sql='SELECT value, updated_at FROM runtime_state WHERE key=?', params=[contract['key']]),
        dict(sql='SELECT value, updated_at FROM runtime_state WHERE key=?', params=['cloudflare_refresh_writer_lock'])]


def _object(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or '{}')
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _number(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except ValueError:
        return None


def _close(a, b, tolerance=MONEY_TOLERANCE):
    left, right = _number(a), _number(b)
    return left is not None and right is not None and abs(left - right) <= tolerance


def assess_nav_cache(*, now: datetime, contract: dict, nav_rows: list[dict],
                     cache_rows: list[dict], lock_rows: list[dict], public: dict) -> dict:
    now = now.astimezone(UTC)
    checks = []
    def add(name, ok, detail, pending=False):
        checks.append(dict(name=name, ok=bool(ok) or pending,
                           state='AVVENTER' if pending else ('OK' if ok else 'AVVIK'), detail=detail))
    def match(name, actual, expected, tolerance=MONEY_TOLERANCE, pending=False):
        add(name, _close(actual, expected, tolerance),
            f'faktisk {actual if _number(actual) is not None else "mangler"}; forventet {expected if _number(expected) is not None else "mangler"}', pending=pending)

    lock = lock_rows[0] if lock_rows else {}
    lease = str(lock.get('value') or '')
    expires = _time(lease.rsplit('|', 1)[-1]) if '|' in lease else None
    heartbeat = _time(lock.get('updated_at'))
    writing = bool(expires and expires > now and heartbeat and timedelta(0) <= now - heartbeat < timedelta(minutes=5))
    rows = {r.get('nav_scope'): r for r in nav_rows}
    core, full = rows.get('CORE', {}), rows.get('FULL', {})
    add('NAV-grunnlag', bool(core and full), 'CORE og FULL fra samme regnskapsdato kreves')

    for scope, row in [('CORE', core), ('FULL', full)]:
        total, shares = _number(row.get('nav_total_nok')), _number(row.get('shares_outstanding'))
        valid = total is not None and shares is not None and shares > 0 and shares == shares.to_integral_value()
        add(f'{scope}: gyldige NAV-tall', valid, 'endelige tall og positivt heltallig aksjeantall')
        if valid:
            match(f'{scope}: NAV per aksje', row.get('nav_per_share_nok'), total / shares, PER_SHARE_TOLERANCE)
            terms = [_number(row.get(k)) for k in ['bemobi_value_nok', 'cash_estimate_nok', 'other_net_assets_nok']]
            expected = sum(terms) if all(v is not None for v in terms) else None
            match(f'{scope}: summering av eiendeler', total, expected)
            price = _number(row.get('otec_price_nok'))
            if total != 0:
                discount = (1 - price / (total / shares)) * 100 if price is not None else None
                match(f'{scope}: NAV-rabatt', row.get('discount_pct'), discount, Decimal('0.0001'))
    if core:
        inputs = _object(core.get('components_json'))
        bmob = _object(inputs.get('bmob3'))
        otec = _object(inputs.get('otec'))
        add('CORE: siste gyldige beholdning', bmob.get('holding_id') == core.get('expected_holding_id') and core.get('expected_holding_id') is not None, 'beholdning som gjelder på NAV-dato', pending=writing)
        add('CORE: siste kjente aksjeantall', otec.get('share_count_id') == core.get('expected_share_count_id') and core.get('expected_share_count_id') is not None, 'siste kildebaserte aksjeantall på NAV-dato', pending=writing)
        add('CORE: kursdato mot grunnlag', core.get('input_price_date') == core.get('expected_price_date') and core.get('expected_price_date') is not None, 'nyeste tilgjengelige BMOB3-dato til og med NAV-dato', pending=writing)
        add('CORE: valutadato mot grunnlag', str(core.get('input_fx_at'))[:10] == core.get('expected_fx_date') and core.get('expected_fx_date') is not None, 'nyeste BRL/NOK-dato til og med NAV-dato', pending=writing)
        values = [_number(core.get(k)) for k in ['input_price_brl', 'input_holding_shares', 'input_brl_nok']]
        valid = all(v is not None and v >= 0 for v in values) and core.get('input_fx_base') == 'BRL' and core.get('input_fx_quote') == 'NOK'
        expected = values[0] * values[1] * values[2] if valid else None
        match('Bemobi: aksjer × kurs × BRL/NOK', core.get('bemobi_value_nok'), expected, pending=writing)
        match('CORE: OTEC-kurs mot grunnlagsrad', core.get('otec_price_nok'), core.get('input_otec_price'), PER_SHARE_TOLERANCE, pending=writing)
        match('CORE: cash mot grunnlagsrad', core.get('cash_estimate_nok'), core.get('input_cash_nok'), pending=writing)
        match('CORE: aksjeantall mot grunnlagsrad', core.get('shares_outstanding'), core.get('input_outstanding'), Decimal('0'), pending=writing)
    if full:
        match('FULL: andre netto eiendeler mot grunnlag', full.get('other_net_assets_nok'), full.get('input_ona_nok'), pending=writing)

    cache_row = cache_rows[0] if cache_rows else {}
    snapshot = _object(cache_row.get('value'))
    generated = _time(snapshot.get('generated_at'))
    add('Cache: versjon', snapshot.get('version') == contract['version'], f'forventet versjon {contract["version"]}')
    add('Cache: alle seksjoner', all(isinstance(snapshot.get(k), dict) for k in contract['components']), 'summary, economic, quotes, buyback og events')
    age = (now - generated).total_seconds() if generated else None
    add('Cache: alder', age is not None and 0 <= age <= contract['max_age'], f'alder {round(age) if age is not None else "ukjent"} sekunder; maks {contract["max_age"]}')

    public = _object(public)
    meta = _object(public.get('meta'))
    add('Nettsiden: gyldig svar og versjon', bool(public) and meta.get('snapshot_version') == contract['version'], 'bootstrap må ha forventet versjon')
    public_generated = _time(meta.get('generated_at'))
    public_age = (now - public_generated).total_seconds() if public_generated else None
    add('Nettsiden: dataenes alder', public_age is not None and 0 <= public_age <= contract['max_age'], 'samme aldersgrense som lagret cache')
    add('Nettsiden: bruker lagret cache', meta.get('source') == 'hot_snapshot', 'live_fallback signaliserer manglende/ugyldig cache')
    recent_build = bool(generated and 0 <= (now - generated).total_seconds() <= 120)
    same_generation = bool(generated and public_generated and generated == public_generated)
    race = writing or (not same_generation and recent_build)
    add('Nettsiden: samme cachegenerasjon', same_generation, 'offentlig svar sammenlignes med D1-cache', pending=race and not same_generation)
    newer_nav = any(_time(r.get('updated_at')) and generated and _time(r.get('updated_at')) > generated for r in nav_rows)
    recent_nav = any(_time(r.get('updated_at')) and 0 <= (now - _time(r.get('updated_at'))).total_seconds() <= 120 for r in nav_rows)
    reconciliation_pending = writing or (newer_nav and recent_nav)
    add('Cache: beregnet etter siste NAV-endring', not newer_nav, 'cache skal dekke siste NAV-oppdatering', pending=newer_nav and reconciliation_pending)

    def check_payload(payload, label, pending):
        summary, economic = _object(payload.get('summary')), _object(payload.get('economic'))
        add(f'{label}: NAV klar', summary.get('ready') is True and economic.get('ready') is True, 'begge NAV-modeller må være klare', pending=pending)
        add(f'{label}: regnskapsdato', bool(full) and summary.get('as_of_date') == str(full.get('as_of_at'))[:10] == economic.get('as_of_date'), 'samme dato som D1 FULL', pending=pending)
        match(f'{label}: regnskaps-NAV mot D1', summary.get('nav_per_share'), full.get('nav_per_share_nok'), PER_SHARE_TOLERANCE, pending=pending)
        match(f'{label}: aksjeantall mot D1', summary.get('shares_outstanding'), full.get('shares_outstanding'), Decimal('0'), pending=pending)
        for public_key, stored_key in [('bemobi_value_mnok', 'bemobi_value_nok'), ('estimated_cash_mnok', 'cash_estimate_nok'), ('other_net_assets_mnok', 'other_net_assets_nok')]:
            amount = _number(summary.get(public_key))
            match(f'{label}: {public_key} mot D1', amount * MILLION if amount is not None else None, full.get(stored_key), pending=pending)
        match(f'{label}: Bemobi-beholdning mot D1', summary.get('bemobi_shares'), core.get('input_holding_shares'), Decimal('0'), pending=pending)

        shares = _number(economic.get('shares_outstanding'))
        total = _number(economic.get('nav_total_mnok'))
        if shares is not None and shares > 0 and total is not None:
            match(f'{label}: investor-NAV per aksje', economic.get('nav_per_share'), total * MILLION / shares, PER_SHARE_TOLERANCE)
        else:
            add(f'{label}: investor-NAV per aksje', False, 'manglende tall eller ugyldig aksjeantall')
        match(f'{label}: investor-aksjer mot D1', shares, full.get('shares_outstanding'), Decimal('0'), pending=pending)
        composition = economic.get('composition')
        amounts = [_number(r.get('amount_mnok')) for r in composition if isinstance(r, dict)] if isinstance(composition, list) else []
        amount = sum(amounts) if amounts and all(v is not None for v in amounts) and len(amounts) == len(composition) else None
        match(f'{label}: investor-NAV summerer', total * MILLION if total is not None else None, amount * MILLION if amount is not None else None)
        component_shares_ok = shares is not None and shares > 0 and bool(amounts) and len(amounts) == len(composition) and all(v is not None for v in amounts)
        if component_shares_ok:
            component_shares_ok = all(_close(r.get('per_share_nok'), value * MILLION / shares, PER_SHARE_TOLERANCE) for r, value in zip(composition, amounts))
        add(f'{label}: komposisjon per aksje', component_shares_ok, 'hver post avstemmes fra mill. NOK til NOK per aksje')

        option_db = _object(_object(_object(full.get('components_json')).get('other_net_assets')).get('option_liability'))
        option_inputs = _object(option_db.get('inputs'))
        count = _number(option_inputs.get('option_count'))
        strike = _number(option_inputs.get('strike_nok', option_db.get('strike_nok')))
        liability = _number(option_db.get('amount_nok'))
        cash_fx = _number(_object(economic.get('cash_fx')).get('adjustment_mnok'))
        life = _object(economic.get('life360'))
        life_adjustment = _number(life.get('adjustment_nok')) if life.get('ready') else Decimal('0')
        costs = _number(_object(economic.get('operating_costs')).get('base_mnok'))
        accounting = _number(full.get('nav_total_nok'))
        terms = [shares, count, strike, liability, cash_fx, life_adjustment, costs, accounting]
        valid = all(v is not None for v in terms) and shares > 0 and count >= 0 and count == count.to_integral_value() and strike >= 0
        expected = None
        if valid:
            before = accounting + liability + cash_fx * MILLION + life_adjustment - costs * MILLION
            after_per_share = before / shares if before / shares <= strike else (before + count * strike) / (shares + count)
            expected = after_per_share
        match(f'{label}: investor-NAV etter opsjonsoppgjør', economic.get('nav_per_share'), expected, PER_SHARE_TOLERANCE, pending=pending)
        conservative_cost = _number(_object(economic.get('operating_costs')).get('conservative_mnok'))
        conservative_expected = None
        if valid and conservative_cost is not None:
            conservative_before = accounting + liability + cash_fx * MILLION + life_adjustment - conservative_cost * MILLION
            conservative_expected = conservative_before / shares if conservative_before / shares <= strike else (conservative_before + count * strike) / (shares + count)
        match(f'{label}: konservativ investor-NAV', economic.get('conservative_nav_per_share'), conservative_expected, PER_SHARE_TOLERANCE, pending=pending)

        if life.get('ready'):
            factors = [_number(life.get(k)) for k in ['shares', 'price', 'fx_rate']]
            market = factors[0] * factors[1] * factors[2] if all(v is not None for v in factors) else None
            match(f'{label}: Life360 aksjer × kurs × USD/NOK', life.get('market_value_nok'), market)
        quote = _object(_object(_object(payload.get('quotes')).get('symbols')).get('OTEC'))
        price, nav = _number(quote.get('last')), _number(economic.get('nav_per_share'))
        discount = (1 - price / nav) * 100 if price is not None and nav is not None and nav != 0 else None
        # Bootstrap synchronizes OTEC/discount with the current quote; raw cache need not.
        if label == 'Nettsiden':
            accounting_nav = _number(summary.get('nav_per_share'))
            accounting_discount = (1 - price / accounting_nav) * 100 if price is not None and accounting_nav is not None and accounting_nav != 0 else None
            match('Nettsiden: regnskaps-NAV-rabatt', summary.get('nav_discount_pct'), accounting_discount, Decimal('0.0001'))
            match('Nettsiden: investor-NAV-rabatt', economic.get('discount_pct'), discount, Decimal('0.0001'))
            match('Nettsiden: samme OTEC-kurs i kortene', summary.get('otec_price'), price, PER_SHARE_TOLERANCE)

    check_payload(snapshot, 'Cache', reconciliation_pending)
    check_payload(public, 'Nettsiden', reconciliation_pending or race)
    return dict(checks=checks, unhealthy=any(not c['ok'] for c in checks))


def render_audit(report: dict) -> str:
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    lines = ['', '## NAV-avstemming og cache', '',
             '| Kontroll | Resultat | Detalj |', '|---|---|---|']
    for row in report['checks']:
        lines.append(f"| {cell(row['name'])} | {row['state']} | {cell(row['detail'])} |")
    return '\n'.join(lines) + '\n'

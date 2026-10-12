"""Deterministic synthetic market-wide CVM archive; no network or database."""
import csv
import hashlib
import io
import json
import statistics
import sys
import time
import zipfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cloudflare/src'))
import bemobi_cvm_financials as cvm  # noqa: E402

FIELDS = ['CD_CVM', 'VERSAO', 'MOEDA', 'ESCALA_MOEDA', 'ORDEM_EXERC',
          'DT_INI_EXERC', 'DT_FIM_EXERC', 'CD_CONTA', 'DS_CONTA', 'VL_CONTA']
LABELS = ['Caixa Líquido Atividades Operacionais',
          'Aquisição de ativos imobilizado e intangível',
          'Depreciação e amortização de ativos',
          'Variações em contas a receber de clientes',
          'Pagamento de empréstimos e financiamentos']

def fixture():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for statement in ('DRE', 'DFC', 'BPA', 'BPP'):
            text = io.StringIO()
            writer = csv.writer(text, delimiter=';', lineterminator='\n')
            writer.writerow(FIELDS)
            for issuer in range(400):
                code = cvm.BEMOBI_CVM_CODE if issuer == 0 else str(10000 + issuer)
                for quarter, end in enumerate(('03-31', '06-30', '09-30'), 1):
                    for account in range(100):
                        account_code = {'DRE': '3.01', 'DFC': '6.01', 'BPA': '1.01.01', 'BPP': '2.01.04'}[statement] if account == 0 else f'9.{account:03}'
                        writer.writerow([code, 1, 'REAL', 'MIL', 'ÚLTIMO', '2026-01-01',
                                         f'2026-{end}', account_code, LABELS[account % len(LABELS)], -1000 * quarter])
            suffix = 'DFC_MI' if statement == 'DFC' else statement
            archive.writestr(f'itr_cia_aberta_{suffix}_con_2026.csv', text.getvalue().encode('cp1252'))
    return buffer.getvalue()

def run():
    payload = fixture()
    output = {'issuers': 400, 'rows_per_statement': 120000, 'zip_bytes': len(payload), 'runs': 5}
    calls = 0
    original = cvm._is_capex_label
    def counted(label):
        nonlocal calls
        calls += 1
        return original(label)
    cvm._is_capex_label = counted
    capex = cvm.parse_capex_accounts_archive(payload, year=2026, document_type='itr')
    cvm._is_capex_label = original
    output['capex_label_calls'] = calls
    output['capex_result_sha256'] = hashlib.sha256(json.dumps([asdict(x) for x in capex], sort_keys=True).encode()).hexdigest()
    for name, fn in (
        ('capex', lambda: cvm.parse_capex_accounts_archive(payload, year=2026, document_type='itr')),
        ('full_year', lambda: cvm._parse_year_financials(year=2026, itr_payload=payload, dfp_payload=None, errors=[])),
    ):
        times = []
        for _ in range(5):
            start = time.perf_counter()
            result = fn()
            times.append(time.perf_counter() - start)
        output[name + '_seconds'] = times
        output[name + '_median_seconds'] = statistics.median(times)
        if name == 'full_year':
            output['full_year_result_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    print(json.dumps(output, indent=2))

if __name__ == '__main__':
    run()

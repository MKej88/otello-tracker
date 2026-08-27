from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Mangler forventet tekst i {path}: {old[:100]!r}")
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")


# Bootstrap-kontrakten må følge nyeste SQLite-migrasjon.
replace_once(
    "backend/app/db/d1_bootstrap.py",
    'LATEST_SQLITE_MIGRATION = "0026"',
    'LATEST_SQLITE_MIGRATION = "0027"',
)

# Sekundær FT-backfill skal kun fylle volum. Sekundær pris skal ikke kunne bli last_close.
for migration in (
    "backend/app/db/migrations/0027_otec_market_activity_backfill.sql",
    "cloudflare/migrations/0018_otec_market_activity_backfill.sql",
):
    replace_once(
        migration,
        "SELECT i.id, v.trading_date, v.volume_shares, v.last_price_nok,\n       s.id, sd.id, 'HISTORICAL_EXPORT',\n       '{\"backfill\":\"MANUALLY_VERIFIED_SECONDARY_HISTORY\",\"source_field\":\"Volume\",\"preferred_runtime_source\":\"EURONEXT\"}'\nFROM (\n    SELECT '2026-08-17' AS trading_date, 53546 AS volume_shares, '17.50' AS last_price_nok\n    UNION ALL SELECT '2026-08-18', 31690, '17.36'\n    UNION ALL SELECT '2026-08-19', 59082, '17.20'\n    UNION ALL SELECT '2026-08-20', 37050, '17.00'\n    UNION ALL SELECT '2026-08-21', 76185, '17.04'\n    UNION ALL SELECT '2026-08-24', 61091, '16.94'\n) v",
        "SELECT i.id, v.trading_date, v.volume_shares, NULL,\n       s.id, sd.id, 'HISTORICAL_EXPORT',\n       '{\"backfill\":\"MANUALLY_VERIFIED_SECONDARY_HISTORY\",\"source_field\":\"Volume\",\"price_semantics\":\"VOLUME_ONLY_NO_SECONDARY_PRICE\",\"preferred_runtime_source\":\"EURONEXT\"}'\nFROM (\n    SELECT '2026-08-17' AS trading_date, 53546 AS volume_shares\n    UNION ALL SELECT '2026-08-18', 31690\n    UNION ALL SELECT '2026-08-19', 59082\n    UNION ALL SELECT '2026-08-20', 37050\n    UNION ALL SELECT '2026-08-21', 76185\n    UNION ALL SELECT '2026-08-24', 61091\n) v",
    )

# D1-baseline/reference seed må ha samme stabile source-identitet som SQLite etter 0027.
replace_once(
    "cloudflare/migrations/0002_reference_data.sql",
    "    ('EURONEXT', 'Euronext', 'EXCHANGE', 'https://live.euronext.com/', 1, 1, 'Primær børs-/meldingskilde for OTEC der bruksvilkår tillater automatisering.'),\n",
    "    ('EURONEXT', 'Euronext', 'EXCHANGE', 'https://live.euronext.com/', 1, 1, 'Primær børs-/meldingskilde for OTEC der bruksvilkår tillater automatisering.'),\n    ('FT_MARKETS', 'Financial Times Markets historical data', 'OTHER', 'https://markets.ft.markitdigital.com/', 0, 1, 'Sekundær offentlig historikktabell brukt kun til eksplisitt kontrollert OTEC-volum-backfill; ingen automatisert scraping.'),\n",
)

# Forventninger som faktisk er endret av den nye migrasjonen.
replace_once(
    "backend/tests/test_buyback_forecast.py",
    '    assert status["to"] == "2026-08-14"',
    '    assert status["to"] == "2026-08-24"',
)

p = Path("backend/tests/test_database.py")
text = p.read_text(encoding="utf-8")
replacements = {
    '        "0025", "0026",\n': '        "0025", "0026", "0027",\n',
    '    assert status["latest_migration"] == "0026"': '    assert status["latest_migration"] == "0027"',
    '    assert status["table_counts"]["sources"] == 17': '    assert status["table_counts"]["sources"] == 18',
    '    assert status["table_counts"]["market_activity"] == 0': '    assert status["table_counts"]["market_activity"] == 6',
    '            assert payload["latest_migration"] == "0026"': '            assert payload["latest_migration"] == "0027"',
    '            assert payload["table_counts"]["sources"] == 17': '            assert payload["table_counts"]["sources"] == 18',
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"Mangler database-testmarkør: {old!r}")
    text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

replace_once(
    "backend/tests/test_otello_report_ingestion.py",
    '    assert \'PHASE = "16.1"\' in scheduled',
    '    assert \'PHASE = "16.2"\' in scheduled',
)

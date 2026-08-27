from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Mangler forventet tekst i {path}: {old[:120]!r}")
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")


# Bootstrap-kontrakten må følge nyeste SQLite-migrasjon.
replace_once(
    "backend/app/db/d1_bootstrap.py",
    'LATEST_SQLITE_MIGRATION = "0026"',
    'LATEST_SQLITE_MIGRATION = "0027"',
)

# Sekundær FT-backfill skal kun fylle volum. Sekundær pris skal ikke kunne bli last_close.
replace_once(
    "backend/app/db/migrations/0027_otec_market_activity_backfill.sql",
    "SELECT i.id, v.trading_date, v.volume_shares, v.last_price_nok,\n       s.id, sd.id, 'HISTORICAL_EXPORT',\n       '{\"backfill\":\"MANUALLY_VERIFIED_SECONDARY_HISTORY\",\"source_field\":\"Volume\",\"preferred_runtime_source\":\"EURONEXT\"}'\nFROM (\n    SELECT '2026-08-17' AS trading_date, 53546 AS volume_shares, '17.50' AS last_price_nok\n    UNION ALL SELECT '2026-08-18', 31690, '17.36'\n    UNION ALL SELECT '2026-08-19', 59082, '17.20'\n    UNION ALL SELECT '2026-08-20', 37050, '17.00'\n    UNION ALL SELECT '2026-08-21', 76185, '17.04'\n    UNION ALL SELECT '2026-08-24', 61091, '16.94'\n) v",
    "SELECT i.id, v.trading_date, v.volume_shares, NULL,\n       s.id, sd.id, 'HISTORICAL_EXPORT',\n       '{\"backfill\":\"MANUALLY_VERIFIED_SECONDARY_HISTORY\",\"source_field\":\"Volume\",\"price_semantics\":\"VOLUME_ONLY_NO_SECONDARY_PRICE\",\"preferred_runtime_source\":\"EURONEXT\"}'\nFROM (\n    SELECT '2026-08-17' AS trading_date, 53546 AS volume_shares\n    UNION ALL SELECT '2026-08-18', 31690\n    UNION ALL SELECT '2026-08-19', 59082\n    UNION ALL SELECT '2026-08-20', 37050\n    UNION ALL SELECT '2026-08-21', 76185\n    UNION ALL SELECT '2026-08-24', 61091\n) v",
)

# D1 deles i en ren reference-identitet (0018) og data-backfill (0019).
# Da får FT_MARKETS samme stabile source-id som SQLite uten at bootstrap-targetet
# forhåndsfylles med market_activity/source_documents før den portable importen.
old_d1 = Path("cloudflare/migrations/0018_otec_market_activity_backfill.sql")
text = old_d1.read_text(encoding="utf-8")
source_block = """-- Reference identity for backend migration 0027.\n-- Keep this source-only so fresh D1 bootstrap targets can establish the same stable\n-- source id as SQLite before importing historical data.\n\nINSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes)\nSELECT 'FT_MARKETS', 'Financial Times Markets historical data', 'OTHER',\n       'https://markets.ft.markitdigital.com/', 0, 1,\n       'Sekundær offentlig historikktabell brukt kun til eksplisitt kontrollert OTEC-volum-backfill; ingen automatisert scraping.'\nWHERE NOT EXISTS (SELECT 1 FROM sources WHERE code='FT_MARKETS');\n"""
marker = "INSERT INTO source_documents(\n"
if marker not in text:
    raise SystemExit("D1 source-document marker mangler")
rest = marker + text.split(marker, 1)[1]
rest = rest.replace(
    "SELECT i.id, v.trading_date, v.volume_shares, v.last_price_nok,\n       s.id, sd.id, 'HISTORICAL_EXPORT',\n       '{\"backfill\":\"MANUALLY_VERIFIED_SECONDARY_HISTORY\",\"source_field\":\"Volume\",\"preferred_runtime_source\":\"EURONEXT\"}'\nFROM (\n    SELECT '2026-08-17' AS trading_date, 53546 AS volume_shares, '17.50' AS last_price_nok\n    UNION ALL SELECT '2026-08-18', 31690, '17.36'\n    UNION ALL SELECT '2026-08-19', 59082, '17.20'\n    UNION ALL SELECT '2026-08-20', 37050, '17.00'\n    UNION ALL SELECT '2026-08-21', 76185, '17.04'\n    UNION ALL SELECT '2026-08-24', 61091, '16.94'\n) v",
    "SELECT i.id, v.trading_date, v.volume_shares, NULL,\n       s.id, sd.id, 'HISTORICAL_EXPORT',\n       '{\"backfill\":\"MANUALLY_VERIFIED_SECONDARY_HISTORY\",\"source_field\":\"Volume\",\"price_semantics\":\"VOLUME_ONLY_NO_SECONDARY_PRICE\",\"preferred_runtime_source\":\"EURONEXT\"}'\nFROM (\n    SELECT '2026-08-17' AS trading_date, 53546 AS volume_shares\n    UNION ALL SELECT '2026-08-18', 31690\n    UNION ALL SELECT '2026-08-19', 59082\n    UNION ALL SELECT '2026-08-20', 37050\n    UNION ALL SELECT '2026-08-21', 76185\n    UNION ALL SELECT '2026-08-24', 61091\n) v",
)
if "last_price_nok" in rest.split("FROM (", 1)[1].split(") v", 1)[0]:
    raise SystemExit("Sekundær D1-backfill inneholder fortsatt pris")
old_d1.unlink()
Path("cloudflare/migrations/0018_otec_market_activity_source.sql").write_text(source_block, encoding="utf-8")
Path("cloudflare/migrations/0019_otec_market_activity_backfill.sql").write_text(
    "-- Production D1 data backfill for backend migration 0027.\n-- Requires 0018_otec_market_activity_source.sql. Runtime activity comes from official Euronext delayed trade files.\n\n" + rest,
    encoding="utf-8",
)

# Bootstrap-testen må etablere den nye reference-identiteten etter eksisterende source-migrasjoner.
p = Path("backend/tests/test_d1_bootstrap.py")
text = p.read_text(encoding="utf-8")
anchor = 'D1_LIFE360_HOLDINGS = ROOT / "cloudflare" / "migrations" / "0017_life360_holding_anchors.sql"\n'
if anchor not in text:
    raise SystemExit("bootstrap constant marker mangler")
text = text.replace(
    anchor,
    anchor + 'D1_OTEC_ACTIVITY_SOURCE = ROOT / "cloudflare" / "migrations" / "0018_otec_market_activity_source.sql"\n',
    1,
)
anchor = '        connection.executescript(D1_LIFE360_HOLDINGS.read_text(encoding="utf-8"))\n'
if anchor not in text:
    raise SystemExit("bootstrap execution marker mangler")
text = text.replace(
    anchor,
    anchor + '        connection.executescript(D1_OTEC_ACTIVITY_SOURCE.read_text(encoding="utf-8"))\n',
    1,
)
p.write_text(text, encoding="utf-8")

# Reference-data-paritet skal inkludere source-only 0018, men ikke data-backfill 0019.
p = Path("backend/tests/test_d1_schema_parity.py")
text = p.read_text(encoding="utf-8")
anchor = 'D1_LIFE360_HOLDINGS = ROOT / "cloudflare" / "migrations" / "0017_life360_holding_anchors.sql"\n'
if anchor not in text:
    raise SystemExit("schema parity constant marker mangler")
text = text.replace(
    anchor,
    anchor + 'D1_OTEC_ACTIVITY_SOURCE = ROOT / "cloudflare" / "migrations" / "0018_otec_market_activity_source.sql"\n',
    1,
)
anchor = '        d1.executescript(D1_LIFE360.read_text(encoding="utf-8"))\n'
if anchor not in text:
    raise SystemExit("schema parity source marker mangler")
text = text.replace(
    anchor,
    anchor + '        d1.executescript(D1_OTEC_ACTIVITY_SOURCE.read_text(encoding="utf-8"))\n',
    1,
)
p.write_text(text, encoding="utf-8")

# Forventninger som faktisk er endret av den nye SQLite-migrasjonen.
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

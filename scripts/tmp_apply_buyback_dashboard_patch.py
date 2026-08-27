from pathlib import Path

repo = Path('.')

# Reference dashboard: compute the latest reported week independently of forecast history.
path = repo / 'backend/app/buybacks/dashboard.py'
text = path.read_text(encoding='utf-8')
old = 'from app.buybacks.forecast import buyback_forecast\n'
new = 'from app.buybacks.forecast import LOOKBACK_DAYS, SAFE_HARBOUR_SHARE, buyback_forecast\n'
if old not in text:
    raise SystemExit('backend forecast import marker missing')
text = text.replace(old, new, 1)
marker = '\ndef _normalize_latest_numeric_fields(payload: dict[str, Any] | None) -> None:\n'
helper = '''\ndef _latest_week_metrics(connection, latest) -> dict[str, int | float | None]:\n    empty = {\n        "market_volume_shares": None,\n        "volume_share_pct": None,\n        "safe_harbour_capacity_shares": None,\n        "safe_harbour_utilization_pct": None,\n    }\n    if latest is None or not latest["period_start"] or not latest["trade_date"]:\n        return empty\n\n    start = str(latest["period_start"])\n    end = str(latest["trade_date"])\n    period_activity = connection.execute(\n        """\n        SELECT ma.trading_date, ma.volume_shares\n        FROM market_activity ma\n        JOIN instruments i ON i.id=ma.instrument_id\n        WHERE i.symbol='OTEC' AND ma.trading_date BETWEEN ? AND ? AND ma.volume_shares > 0\n        ORDER BY ma.trading_date\n        """,\n        (start, end),\n    ).fetchall()\n    market_volume = sum(int(row["volume_shares"]) for row in period_activity)\n    actual = int(latest["shares"] or 0)\n    result = {\n        **empty,\n        "market_volume_shares": market_volume or None,\n        "volume_share_pct": round(actual / market_volume * 100, 2) if market_volume else None,\n    }\n\n    lookback = connection.execute(\n        """\n        SELECT ma.volume_shares\n        FROM market_activity ma\n        JOIN instruments i ON i.id=ma.instrument_id\n        WHERE i.symbol='OTEC' AND ma.trading_date < ? AND ma.volume_shares > 0\n        ORDER BY ma.trading_date DESC, ma.id DESC\n        LIMIT ?\n        """,\n        (start, LOOKBACK_DAYS),\n    ).fetchall()\n    if len(lookback) < LOOKBACK_DAYS or not period_activity:\n        return result\n\n    adv20 = sum(int(row["volume_shares"]) for row in lookback) / LOOKBACK_DAYS\n    max_shares = int(latest["max_shares"] or 0)\n    cumulative = int(latest["cumulative_program_shares"] or 0)\n    previous_cumulative = max(0, cumulative - actual)\n    raw_capacity = float(SAFE_HARBOUR_SHARE) * adv20 * len(period_activity)\n    capacity = (\n        min(raw_capacity, float(max(0, max_shares - previous_cumulative)))\n        if max_shares\n        else raw_capacity\n    )\n    if capacity <= 0:\n        return result\n    result["safe_harbour_capacity_shares"] = round(capacity)\n    result["safe_harbour_utilization_pct"] = round(actual / capacity * 100, 1)\n    return result\n\n'''
if marker not in text:
    raise SystemExit('backend helper insertion marker missing')
text = text.replace(marker, helper + marker, 1)
old_hist = '''        history = _enrich_history(\n            raw_history,\n            _market_volumes(connection, raw_history),\n        )\n'''
if old_hist not in text:
    raise SystemExit('backend history marker missing')
text = text.replace(old_hist, old_hist + '        latest_metrics = _latest_week_metrics(connection, latest)\n', 1)
start = text.index('    if latest_payload is not None:\n        matching = next(')
end = text.index('\n\n    shares = None', start)
text = text[:start] + '    if latest_payload is not None:\n        latest_payload.update(latest_metrics)\n' + text[end:]
path.write_text(text, encoding='utf-8')

# Cloudflare Worker dashboard parity.
path = repo / 'cloudflare/src/buyback_dashboard.py'
text = path.read_text(encoding='utf-8')
old = 'from buyback_service import buyback_forecast\n'
new = 'from buyback_service import LOOKBACK_DAYS, SAFE_HARBOUR_SHARE, buyback_forecast\n'
if old not in text:
    raise SystemExit('worker forecast import marker missing')
text = text.replace(old, new, 1)
marker = '\ndef _normalize_latest_numeric_fields(payload: dict[str, Any] | None) -> None:\n'
helper = '''\nasync def _latest_week_metrics(repository, latest) -> dict[str, int | float | None]:\n    empty = {\n        "market_volume_shares": None,\n        "volume_share_pct": None,\n        "safe_harbour_capacity_shares": None,\n        "safe_harbour_utilization_pct": None,\n    }\n    if latest is None or not latest.get("period_start") or not latest.get("trade_date"):\n        return empty\n\n    start = str(latest["period_start"])\n    end = str(latest["trade_date"])\n    period_activity = await repository.all(\n        """\n        SELECT ma.trading_date, ma.volume_shares\n        FROM market_activity ma\n        JOIN instruments i ON i.id=ma.instrument_id\n        WHERE i.symbol='OTEC' AND ma.trading_date BETWEEN ? AND ? AND ma.volume_shares > 0\n        ORDER BY ma.trading_date\n        """,\n        (start, end),\n    )\n    market_volume = sum(int(row["volume_shares"]) for row in period_activity)\n    actual = int(latest.get("shares") or 0)\n    result = {\n        **empty,\n        "market_volume_shares": market_volume or None,\n        "volume_share_pct": round(actual / market_volume * 100, 2) if market_volume else None,\n    }\n\n    lookback = await repository.all(\n        """\n        SELECT ma.volume_shares\n        FROM market_activity ma\n        JOIN instruments i ON i.id=ma.instrument_id\n        WHERE i.symbol='OTEC' AND ma.trading_date < ? AND ma.volume_shares > 0\n        ORDER BY ma.trading_date DESC, ma.id DESC\n        LIMIT ?\n        """,\n        (start, LOOKBACK_DAYS),\n    )\n    if len(lookback) < LOOKBACK_DAYS or not period_activity:\n        return result\n\n    adv20 = sum(int(row["volume_shares"]) for row in lookback) / LOOKBACK_DAYS\n    max_shares = int(latest.get("max_shares") or 0)\n    cumulative = int(latest.get("cumulative_program_shares") or 0)\n    previous_cumulative = max(0, cumulative - actual)\n    raw_capacity = float(SAFE_HARBOUR_SHARE) * adv20 * len(period_activity)\n    capacity = (\n        min(raw_capacity, float(max(0, max_shares - previous_cumulative)))\n        if max_shares\n        else raw_capacity\n    )\n    if capacity <= 0:\n        return result\n    result["safe_harbour_capacity_shares"] = round(capacity)\n    result["safe_harbour_utilization_pct"] = round(actual / capacity * 100, 1)\n    return result\n\n'''
if marker not in text:
    raise SystemExit('worker helper insertion marker missing')
text = text.replace(marker, helper + marker, 1)
old_hist = '    history = _enrich_history(raw_history, volumes)\n'
if old_hist not in text:
    raise SystemExit('worker history marker missing')
text = text.replace(old_hist, old_hist + '    latest_metrics = await _latest_week_metrics(repository, latest)\n', 1)
start = text.index('    if latest_payload is not None:\n        matching = next(')
end = text.index('\n\n    shares = None', start)
text = text[:start] + '    if latest_payload is not None:\n        latest_payload.update(latest_metrics)\n' + text[end:]
path.write_text(text, encoding='utf-8')

# Worker NewsWeb ingestion: source-backed maximum purchase price.
path = repo / 'cloudflare/src/newsweb_buybacks.py'
text = path.read_text(encoding='utf-8')
marker = '''def _decimal(value: str) -> Decimal:\n    return Decimal(value.replace(",", "").strip())\n'''
addition = marker + '''\n\ndef _parse_max_program_price(text: str) -> Decimal | None:\n    clean = normalize_weekly_body(text)\n    match = re.search(\n        r"maximum consideration to be paid for shares acquired under (?:this |the )?buyback program is NOK ([\\d.,]+) per share",\n        clean,\n        re.I,\n    )\n    return _decimal(match.group(1)) if match is not None else None\n'''
if marker not in text:
    raise SystemExit('NewsWeb decimal marker missing')
text = text.replace(marker, addition, 1)
old = '''    metadata = {"parser": "otec-buyback-status-v1", **_message_metadata(message)}\n    document_id = await repository.create_source_document(\n'''
new = '''    max_price = _parse_max_program_price(message.body)\n    metadata = {\n        "parser": "otec-buyback-status-v2-program-cap",\n        **_message_metadata(message),\n        "max_price_nok": decimal_text(max_price) if max_price is not None else None,\n    }\n    document_id = await repository.create_source_document(\n'''
if old not in text:
    raise SystemExit('NewsWeb metadata marker missing')
text = text.replace(old, new, 1)
text = text.replace(
    '"SELECT id, max_shares, source_document_id FROM buyback_programs WHERE external_program_id=? LIMIT 1",',
    '"SELECT id, max_shares, max_price_nok, source_document_id FROM buyback_programs WHERE external_program_id=? LIMIT 1",',
)
old = '''            INSERT INTO buyback_programs(\n                external_program_id, announced_at, start_date, max_shares,\n                status, source_document_id, notes\n            ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?)\n'''
new = '''            INSERT INTO buyback_programs(\n                external_program_id, announced_at, start_date, max_shares, max_price_nok,\n                status, source_document_id, notes\n            ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)\n'''
if old not in text:
    raise SystemExit('NewsWeb insert marker missing')
text = text.replace(old, new, 1)
old = '''                parsed.max_program_shares,\n                document_id,\n                "Program reconstructed from NEWSWEB mirror of Oslo Bors status; initiation document can supersede this source later.",\n'''
new = '''                parsed.max_program_shares,\n                decimal_text(max_price) if max_price is not None else None,\n                document_id,\n                "Program reconstructed from NEWSWEB mirror of Oslo Bors status; initiation document can supersede this source later.",\n'''
if old not in text:
    raise SystemExit('NewsWeb insert params marker missing')
text = text.replace(old, new, 1)
old = '''    else:\n        old_priority = await _source_priority(repository, int(program["source_document_id"]))\n        new_priority = await _source_priority(repository, document_id)\n        same_document = int(program["source_document_id"]) == document_id\n'''
new = '''    else:\n        stored_max_price = (\n            Decimal(str(program["max_price_nok"]))\n            if program.get("max_price_nok") is not None\n            else None\n        )\n        if max_price is not None and stored_max_price is not None and stored_max_price != max_price:\n            raise ValueError(\n                f"NewsWeb max_price_nok avviker fra lagret programvilkår: lagret={stored_max_price}, kandidat={max_price}"\n            )\n        old_priority = await _source_priority(repository, int(program["source_document_id"]))\n        new_priority = await _source_priority(repository, document_id)\n        same_document = int(program["source_document_id"]) == document_id\n'''
if old not in text:
    raise SystemExit('NewsWeb existing marker missing')
text = text.replace(old, new, 1)
old = '''        if same_document or new_priority < old_priority:\n            await repository.run(\n                "UPDATE buyback_programs SET max_shares=?, source_document_id=? WHERE id=?",\n                (parsed.max_program_shares, document_id, int(program["id"])),\n            )\n\n    program_id = int(program["id"])\n'''
new = '''        if same_document or new_priority < old_priority:\n            await repository.run(\n                "UPDATE buyback_programs SET max_shares=?, max_price_nok=COALESCE(?, max_price_nok), source_document_id=? WHERE id=?",\n                (\n                    parsed.max_program_shares,\n                    decimal_text(max_price) if max_price is not None else None,\n                    document_id,\n                    int(program["id"]),\n                ),\n            )\n        elif max_price is not None and program.get("max_price_nok") is None:\n            await repository.run(\n                "UPDATE buyback_programs SET max_price_nok=? WHERE id=?",\n                (decimal_text(max_price), int(program["id"])),\n            )\n\n    program_id = int(program["id"])\n    if max_price is not None:\n        existing_provenance = await repository.first(\n            """\n            SELECT 1 FROM provenance_records\n            WHERE entity_table='buyback_programs' AND entity_id=?\n              AND field_name='max_price_nok' AND source_document_id=?\n            LIMIT 1\n            """,\n            (program_id, document_id),\n        )\n        if existing_provenance is None:\n            await repository.run(\n                """\n                INSERT INTO provenance_records(\n                    entity_table, entity_id, field_name, source_document_id,\n                    source_locator, extraction_method, confidence, extracted_value\n                ) VALUES ('buyback_programs', ?, 'max_price_nok', ?, ?, 'PARSER', 'HIGH', ?)\n                """,\n                (\n                    program_id,\n                    document_id,\n                    "Maximum consideration sentence in weekly NewsWeb status",\n                    decimal_text(max_price),\n                ),\n            )\n'''
if old not in text:
    raise SystemExit('NewsWeb update marker missing')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')

# Investor-facing labels.
path = repo / 'frontend/src/BuybackPage.tsx'
text = path.read_text(encoding='utf-8')
replacements = {
    'PRICE_CAP_BLOCKED: "PRISGRENSE"': 'PRICE_CAP_BLOCKED: "MAKS KJØPSPRIS"',
    'TIGHT: "NÆR PRISGRENSE"': 'TIGHT: "NÆR MAKS KJØPSPRIS"',
    'ABOVE_CAP: "OVER PRISGRENSE"': 'ABOVE_CAP: "OVER MAKS KJØPSPRIS"',
    'programmets prisgrense': 'programmets maksimale kjøpspris',
    '<div><span>Prisgrense</span><strong>{value(price?.program_cap_nok, 2)} kr</strong></div>': '<div><span>Maks kjøpspris</span><strong>{value(price?.program_cap_nok, 2)} kr</strong></div>',
    '<div><span>Avstand til prisgrense</span><strong>{value(price?.headroom_pct, 1)} %</strong></div>': '<div><span>Avstand til maks kjøpspris</span><strong>{value(price?.headroom_pct, 1)} %</strong></div>',
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f'frontend marker missing: {old}')
    text = text.replace(old, new)
path.write_text(text, encoding='utf-8')

# Dashboard regression.
path = repo / 'backend/tests/test_buyback_investor_dashboard.py'
text = path.read_text(encoding='utf-8')
if 'test_latest_week_metrics_do_not_depend_on_forecast_history' in text:
    raise SystemExit('dashboard regression already exists')
text += '''\n\ndef test_latest_week_metrics_do_not_depend_on_forecast_history(tmp_path: Path) -> None:\n    database = _database(tmp_path)\n    expected = reference_dashboard(database, as_of_date="2026-08-29")\n    latest = expected["latest_week"]\n    assert latest["market_volume_shares"] is not None\n    assert latest["volume_share_pct"] is not None\n    assert latest["safe_harbour_capacity_shares"] is not None\n    assert latest["safe_harbour_utilization_pct"] is not None\n\n    actual = asyncio.run(\n        worker_dashboard(SQLiteAsyncRepository(database), as_of_date="2026-08-29")\n    )\n    assert actual == expected\n'''
path.write_text(text, encoding='utf-8')

# NewsWeb max-price regression.
path = repo / 'backend/tests/test_cloudflare_newsweb_ingestion.py'
text = path.read_text(encoding='utf-8')
if 'test_worker_newsweb_persists_disclosed_maximum_purchase_price_with_provenance' in text:
    raise SystemExit('NewsWeb regression already exists')
text += '''\n\ndef test_worker_newsweb_persists_disclosed_maximum_purchase_price_with_provenance() -> None:\n    repository = SqliteD1Repository()\n    try:\n        body = FIRST_WEEK_2023.replace("NOK 15 per share", "NOK 20 per share")\n        message = _message(990001, "Otello Corporation share buyback program status", body=body)\n        parsed = parse_newsweb_weekly_status(body)\n        asyncio.run(ingest_weekly_buyback(repository, message, parsed))\n\n        program = repository.connection.execute(\n            "SELECT id, max_price_nok FROM buyback_programs WHERE external_program_id=?",\n            (parsed.program_external_id,),\n        ).fetchone()\n        assert program is not None\n        assert str(program["max_price_nok"]) == "20"\n        provenance = repository.connection.execute(\n            """\n            SELECT pr.extracted_value, pr.extraction_method, pr.confidence, sd.url\n            FROM provenance_records pr\n            JOIN source_documents sd ON sd.id=pr.source_document_id\n            WHERE pr.entity_table='buyback_programs' AND pr.entity_id=?\n              AND pr.field_name='max_price_nok'\n            """,\n            (int(program["id"]),),\n        ).fetchone()\n        assert provenance is not None\n        assert provenance["extracted_value"] == "20"\n        assert provenance["extraction_method"] == "PARSER"\n        assert provenance["confidence"] == "HIGH"\n        assert provenance["url"] == message.public_url\n    finally:\n        repository.connection.close()\n'''
path.write_text(text, encoding='utf-8')

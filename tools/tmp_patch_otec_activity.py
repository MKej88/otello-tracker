from pathlib import Path

path = Path("cloudflare/src/scheduled.py")
text = path.read_text(encoding="utf-8")

try_import = "    from .oslo_calendar import is_oslo_bors_trading_day\n"
try_add = try_import + "    from .otec_activity import refresh_otec_daily_activity\n"
if "from .otec_activity import refresh_otec_daily_activity" not in text:
    if try_import not in text:
        raise SystemExit("try import marker missing")
    text = text.replace(try_import, try_add, 1)

except_import = "    from oslo_calendar import is_oslo_bors_trading_day\n"
except_add = except_import + "    from otec_activity import refresh_otec_daily_activity\n"
if "from otec_activity import refresh_otec_daily_activity" not in text:
    if except_import not in text:
        raise SystemExit("except import marker missing")
    text = text.replace(except_import, except_add, 1)

text = text.replace('PHASE = "16.1"', 'PHASE = "16.2"', 1)

marker = '''    if renew_lock is not None:
        await renew_lock("after OTEC")
'''
addition = '''    otec_activity = await _safe_async_step(
        "otec_activity",
        lambda: refresh_otec_daily_activity(repository, now=scheduled_at),
        steps=steps,
        errors=errors,
        timings_ms=timings_ms,
    )
    if isinstance(otec_activity, dict):
        records_written += int(otec_activity.get("written") or 0)

    if renew_lock is not None:
        await renew_lock("after OTEC")
'''
if '"otec_activity"' not in text:
    if marker not in text:
        raise SystemExit("OTEC integration marker missing")
    text = text.replace(marker, addition, 1)

path.write_text(text, encoding="utf-8")

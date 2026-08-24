from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import bemobi_web_refresh_runtime as runtime  # noqa: E402
import bemobi_web_refresh_v2 as legacy_v2  # noqa: E402


def test_v2_import_path_is_only_a_runtime_compatibility_shim() -> None:
    assert legacy_v2.refresh_bemobi_web is runtime.refresh_bemobi_web
    assert legacy_v2.sync_marketscreener_consensus is runtime.sync_marketscreener_consensus
    assert legacy_v2.parse_forward_consensus_html is runtime.parse_forward_consensus_html
    assert legacy_v2._ensure_consensus_event is runtime._ensure_consensus_event


def test_runtime_module_keeps_dynamic_forward_consensus_contract() -> None:
    html = """
    <table>
      <tr><th></th><th>2027</th><th>2028</th><th>2029</th></tr>
      <tr><td>Net sales</td><td>1002</td><td>1180</td><td>1350</td></tr>
      <tr><td>EBITDA</td><td>342.5</td><td>401.0</td><td>455.0</td></tr>
      <tr><td>EBIT</td><td>257.1</td><td>306.0</td><td>350.0</td></tr>
      <tr><td>Net income</td><td>191.6</td><td>224.0</td><td>260.0</td></tr>
      <tr><td>EPS</td><td>2.16</td><td>2.55</td><td>2.95</td></tr>
      <tr><td>Net debt</td><td>-208</td><td>-180</td><td>-150</td></tr>
    </table>
    """
    years = runtime.parse_forward_consensus_html(html, as_of_year=2028)
    assert [item["year"] for item in years] == [2028, 2029]


def test_secondary_web_sources_are_rotated_across_three_nights() -> None:
    slots = {
        runtime._secondary_refresh_slot(day)
        for day in ("2026-08-21", "2026-08-22", "2026-08-23")
    }
    assert slots == {"result_release", "consensus", "xp_preview"}
    assert len(runtime._SECONDARY_REFRESH_SLOTS) == 3


def test_scheduled_secondary_skip_is_not_a_source_failure() -> None:
    skipped = runtime._scheduled_skip("consensus", "result_release")
    assert skipped == {
        "status": "skipped",
        "reason": "rotating_cpu_budget",
        "slot": "consensus",
        "active_slot": "result_release",
        "rows_written": 0,
    }

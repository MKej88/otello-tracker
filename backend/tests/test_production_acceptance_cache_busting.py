from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloudflare.yml"


def _acceptance_step() -> str:
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    return source.split("      - name: Production HTTP acceptance\n", 1)[1].split(
        "\n      - name: Roll back Worker after failed production acceptance", 1
    )[0]


def test_production_acceptance_uses_unique_cache_buster_for_worker_api() -> None:
    step = _acceptance_step()

    assert "EXPECTED_SHA: ${{ inputs.tested_sha || github.sha }}" in step
    assert 'acceptance_token="${EXPECTED_SHA}-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in step
    assert 'q="acceptance=${acceptance_token}"' in step

    assert '"$base/api/dashboard/bootstrap?${q}"' in step
    assert '"$base/api/dashboard/summary?${q}"' in step
    assert '"$base/api/dashboard/economic?${q}"' in step
    assert '"$base/api/market/quotes?${q}"' in step
    assert '"$base/api/dashboard/history?days=365&max_points=300&${q}"' in step


def test_production_acceptance_validates_bootstrap_payload() -> None:
    step = _acceptance_step()

    assert "/tmp/otello-bootstrap.json" in step
    assert "bootstrap = json.loads(Path('/tmp/otello-bootstrap.json').read_text())" in step
    assert "bootstrap_summary.get('ready') is True" in step
    assert "bootstrap_economic.get('ready') is True" in step
    assert "bootstrap_economic['conservative_nav_per_share'] <= bootstrap_economic['nav_per_share']" in step
    assert "bootstrap_quotes.get('ready') is True" in step
    assert "bootstrap_meta.get('snapshot_version') == 2" in step

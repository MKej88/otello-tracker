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


def test_production_acceptance_waits_for_exact_worker_revision() -> None:
    step = _acceptance_step()

    assert "revision_ready=0" in step
    assert "for attempt in $(seq 1 60)" in step
    assert "revision_probe=${attempt}" in step
    assert "payload.get('revision') or ''" in step
    assert 'if [ "$active_revision" = "$EXPECTED_SHA" ]' in step
    assert "Custom domain did not serve expected Worker revision" in step
    assert "health.get('revision') == os.environ['EXPECTED_SHA']" in step


def test_production_acceptance_validates_bootstrap_payload() -> None:
    step = _acceptance_step()

    assert "/tmp/otello-bootstrap.json" in step
    assert "bootstrap = json.loads(Path('/tmp/otello-bootstrap.json').read_text())" in step
    assert "bootstrap_summary.get('ready') is True" in step
    assert "bootstrap_economic.get('ready') is True" in step
    assert "bootstrap_economic['conservative_nav_per_share'] <= bootstrap_economic['nav_per_share']" in step
    assert "bootstrap_quotes.get('ready') is True" in step
    assert "snapshot_version = bootstrap_meta.get('snapshot_version')" in step
    assert "isinstance(snapshot_version, int) and snapshot_version > 0" in step


def test_production_acceptance_requires_source_backed_life360_holding() -> None:
    step = _acceptance_step()

    assert "life360_details = life360.get('details') or {}" in step
    assert "isinstance(life360_shares, int) and life360_shares >= 0" in step
    assert "life360_details.get('holding_effective_from')" in step
    assert "life360_details.get('holding_quality')" in step
    assert "life360_details.get('holding_basis')" in step
    assert "life360_details.get('holding_source_document_id')" in step
    assert "life360_details.get('report_holding_source_document_id')" in step
    assert "float(life360.get('amount_mnok') or 0) > 0" not in step

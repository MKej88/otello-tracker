from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloudflare.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_auto_deploy_is_called_only_after_complete_main_ci_and_uses_tested_sha() -> None:
    deploy = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    ci = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_run:" not in deploy
    assert "workflow_call:" in deploy
    assert "tested_sha:" in deploy
    assert "required: true" in deploy
    assert "inputs.tested_sha != ''" in deploy
    assert "inputs.tested_sha == github.sha" in deploy
    assert "ref: ${{ inputs.tested_sha || github.sha }}" in deploy
    assert "EXPECTED_SHA: ${{ inputs.tested_sha || github.sha }}" in deploy
    assert "OTELLO_DEPLOYMENT_REVISION: ${{ inputs.tested_sha || github.sha }}" in deploy
    assert "variables['DEPLOYMENT_REVISION'] == os.environ['OTELLO_DEPLOYMENT_REVISION']" in deploy
    assert "git rev-parse HEAD" in deploy

    assert "  deploy-production:" in ci
    deploy_job = ci.split("  deploy-production:\n", 1)[1]
    assert "needs: [backend, frontend, d1-parity, worker, docker-reference]" in deploy_job
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in deploy_job
    assert "uses: ./.github/workflows/deploy-cloudflare.yml" in deploy_job
    assert "tested_sha: ${{ github.sha }}" in deploy_job
    assert "secrets: inherit" not in deploy_job
    assert "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}" in deploy_job
    assert "CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}" in deploy_job
    assert "CLOUDFLARE_D1_DATABASE_ID: ${{ secrets.CLOUDFLARE_D1_DATABASE_ID }}" in deploy_job


def test_environment_scoped_auto_deploy_variable_is_resolved_after_environment_assignment() -> None:
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "  gate:" in source
    assert "environment: production" in source
    assert "AUTO_DEPLOY_ENABLED: ${{ vars.CLOUDFLARE_DEPLOY_ENABLED }}" in source
    assert "if: needs.gate.outputs.deploy == 'true'" in source
    assert "needs: gate" in source

    job_gate = source.split("  gate:\n", 1)[1].split("\n  deploy:\n", 1)[0]
    assert "vars.CLOUDFLARE_DEPLOY_ENABLED == 'true'" not in job_gate


def test_manual_production_deploy_is_limited_to_main() -> None:
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "github.event_name == 'workflow_dispatch'" in source
    assert "github.ref == 'refs/heads/main'" in source


def test_production_checkout_does_not_persist_git_credentials() -> None:
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    checkout = source.split("uses: actions/checkout@", 1)[1].split("\n\n", 1)[0]
    assert "persist-credentials: false" in checkout

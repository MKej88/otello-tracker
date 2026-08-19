from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloudflare.yml"


def test_auto_deploy_waits_for_successful_main_ci_and_uses_tested_sha() -> None:
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert 'workflow_run:' in source
    assert 'workflows: ["CI"]' in source
    assert 'types: [completed]' in source
    assert "github.event.workflow_run.event == 'push'" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert "github.event.workflow_run.conclusion == 'success'" in source
    assert "github.event.workflow_run.head_sha" in source
    assert "EXPECTED_SHA" in source
    assert "git rev-parse HEAD" in source


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

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
    assert "vars.CLOUDFLARE_DEPLOY_ENABLED == 'true'" in source
    assert "github.event.workflow_run.head_sha" in source
    assert "EXPECTED_SHA" in source
    assert "git rev-parse HEAD" in source


def test_manual_production_deploy_is_limited_to_main() -> None:
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "github.event_name == 'workflow_dispatch'" in source
    assert "github.ref == 'refs/heads/main'" in source

from __future__ import annotations

from pathlib import Path
import importlib.util
import subprocess

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


def test_production_acceptance_does_not_hardcode_hot_snapshot_version() -> None:
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "snapshot_version = bootstrap_meta.get('snapshot_version')" in source
    assert "isinstance(snapshot_version, int) and snapshot_version > 0" in source
    assert "bootstrap_meta.get('snapshot_version') ==" not in source


def test_native_workflow_schedule_removal_is_verified_from_cloudflare():
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    cleanup = source.split('      - name: Clear legacy Workflow schedule', 1)[1].split('      - name: Production HTTP acceptance', 1)[0]
    assert "'schedules': []" in cleanup
    assert 'with urlopen(verify, timeout=30)' in cleanup
    assert "state['result'].get('schedules')" in cleanup
    assert 'still active after removal' in cleanup


def test_only_superseded_pull_request_runs_can_be_cancelled() -> None:
    for path, prefix in (
        (CI_WORKFLOW, "ci"),
        (CI_WORKFLOW.parent / "production-config-ci.yml", "production-config"),
    ):
        source = path.read_text(encoding="utf-8")
        block = source.split("\nconcurrency:\n", 1)[1].split("\n\n", 1)[0]
        assert block == (
            "  group: " + prefix + "-${{ github.event_name == 'pull_request' && "
            "format('pr-{0}', github.event.pull_request.number) || "
            "format('run-{0}', github.run_id) }}\n"
            "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}"
        )
    assert "cancel-in-progress: true" not in DEPLOY_WORKFLOW.read_text(encoding="utf-8")


def test_scope_checks_live_ancestor_not_only_last_commit(tmp_path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("production_deploy_scope", ROOT / "tools/production_deploy_scope.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()

    def commit(path, content):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", path)
        return git("rev-parse", "HEAD")

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    live = commit("cloudflare/src/worker.py", "old")
    docs = commit("docs/runbook.md", "documentation")
    assert not module.deploy_required(live, docs)
    diagnostics = commit("frontend/tools/production-performance.mjs", "offline")
    assert not module.deploy_required(live, diagnostics)
    runtime = commit("cloudflare/src/worker.py", "new")
    later_docs = commit("README.md", "another change")
    assert module.deploy_required(live, later_docs)
    assert not module.deploy_required(runtime, later_docs)
    assert module.deploy_required(None, later_docs)
    assert module.deploy_required("0" * 40, later_docs)
    assert module.deploy_required(later_docs, live)
    unknown = commit("frontend/package.json", "{}")
    assert module.deploy_required(later_docs, unknown)
    assert module.deploy_required(unknown, unknown) is False

    for path in ("cloudflare/migrations/1000.sql", "cloudflare/wrangler.jsonc",
                 "frontend/src/App.tsx", "frontend/tools/check-inline-csp.mjs",
                 ".github/workflows/deploy-cloudflare.yml", "docs/input.json"):
        assert not module.offline_only([path])


def test_scope_is_only_used_after_main_ci_and_manual_deploy_remains_available() -> None:
    source = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    assert "fetch-depth: 0" in source
    assert "run: python3 tools/production_deploy_scope.py" in source
    assert 'if [ "$GITHUB_EVENT_NAME" = "workflow_dispatch" ]; then' in source
    assert 'if [ "$DEPLOY_REQUIRED" = "false" ]; then' in source
    assert "if: needs.gate.outputs.deploy == 'true'" in source

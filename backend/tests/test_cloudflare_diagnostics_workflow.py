from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-workflow-diagnostics.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_cloudflare_diagnostics_runs_after_nightly_full_refresh() -> None:
    workflow = _workflow_text()
    assert 'cron: "30 4 * * *"' in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "'otello-full-refresh'" in workflow
    assert "'latest'" in workflow


def test_cloudflare_diagnostics_reads_d1_without_write_operations() -> None:
    workflow = _workflow_text()
    assert "/d1/database" in workflow
    assert "/query" in workflow
    assert "FROM job_runs" in workflow
    assert "FROM source_health" in workflow
    assert "FROM fx_rates" in workflow
    assert "FROM nav_snapshots" in workflow
    assert "CLOUDFLARE_D1_DATABASE_NAME || 'otello-nav'" in workflow

    sql_mutations = (
        "INSERT INTO ",
        "UPDATE ",
        "DELETE FROM ",
        "DROP TABLE ",
        "ALTER TABLE ",
        "CREATE TABLE ",
        "/import",
    )
    for mutation in sql_mutations:
        assert mutation not in workflow


def test_cloudflare_diagnostics_uses_dedicated_read_only_token() -> None:
    workflow = _workflow_text()
    assert "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_READ_TOKEN }}" in workflow
    assert "GitHub secret CLOUDFLARE_READ_TOKEN mangler" in workflow
    assert "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}" not in workflow


def test_manual_diagnostics_reports_old_failure_without_failing_probe() -> None:
    workflow = _workflow_text()
    assert "id: workflow_report" in workflow
    assert "production_unhealthy=" in workflow
    assert "Diagnostikken fant en feilet Cloudflare Workflow-instans" in workflow
    assert "github.event_name == 'schedule'" in workflow
    assert "steps.workflow_report.outputs.production_unhealthy == 'true'" in workflow
    assert "Den valgte Cloudflare Workflow-instansen har feilet" not in workflow


def test_cloudflare_diagnostics_keeps_minimal_github_permissions() -> None:
    workflow = _workflow_text()
    assert "permissions:\n  contents: read" in workflow
    assert "contents: write" not in workflow
    assert "issues: write" not in workflow
    assert "pull-requests: write" not in workflow


def test_cloudflare_diagnostics_sanitizes_d1_errors_before_logging() -> None:
    workflow = _workflow_text()
    assert "[REDACTED]" in workflow
    assert "[REDACTED_EMAIL]" in workflow
    assert "d1-query.json" in workflow
    assert "print(payload)" not in workflow
    assert "print(result)" not in workflow


def test_monitoring_runs_after_changes_and_feeds_existing_deviation_alert():
    workflow = _workflow_text()
    assert 'cloudflare/src/production_monitor.py' in workflow
    assert 'batch.extend(monitoring_queries(' in workflow
    assert 'len(result) != 12' in workflow
    assert 'monitoring = assess_production(' in workflow
    assert 'if monitoring["unhealthy"] or nav_audit["unhealthy"]:' in workflow
    assert 'render_monitoring(monitoring)' in workflow
    assert "github.event_name == 'schedule' || github.event_name == 'push'" in workflow


def test_nav_cache_audit_reads_public_bootstrap_and_database_without_extra_secrets():
    workflow = _workflow_text()
    assert 'audit_queries(audit_contract())' in workflow
    assert '/api/dashboard/bootstrap' in workflow
    assert 'Cache-Control: no-cache' in workflow
    assert 'nav_audit = assess_nav_cache(' in workflow
    assert 'render_audit(nav_audit)' in workflow
    assert 'cloudflare/src/nav_cache_audit.py' in workflow

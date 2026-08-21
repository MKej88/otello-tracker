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

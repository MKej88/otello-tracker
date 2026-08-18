from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "cloudflare" / "tools" / "render_production_config.py"


def _load_renderer():
    spec = importlib.util.spec_from_file_location("render_production_config", RENDERER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_config() -> dict:
    return {
        "name": "otello-tracker-local",
        "main": "src/entry.py",
        "compatibility_date": "2026-08-17",
        "compatibility_flags": ["python_workers", "python_workflows"],
        "triggers": {"crons": ["*/30 * * * *"]},
        "workflows": [
            {
                "name": "otello-full-refresh",
                "binding": "FULL_REFRESH",
                "class_name": "FullRefreshWorkflow",
                "schedules": ["30 3 * * *"],
            }
        ],
        "assets": {"directory": "../frontend/dist", "binding": "ASSETS"},
        "d1_databases": [
            {
                "binding": "DB",
                "database_name": "otello-nav-local",
                "database_id": "00000000-0000-0000-0000-000000000001",
                "migrations_dir": "migrations",
            }
        ],
        "r2_buckets": [
            {"binding": "SOURCE_ARCHIVE", "bucket_name": "otello-source-archive-local"}
        ],
    }


def test_renderer_produces_paid_guardrails_and_workers_dev_bootstrap() -> None:
    renderer = _load_renderer()
    config = renderer.render_config(
        _base_config(),
        worker_name="otello-tracker",
        d1_database_id="11111111-2222-3333-4444-555555555555",
        d1_database_name="otello-nav",
        r2_bucket_name="otello-source-archive",
    )
    assert config["name"] == "otello-tracker"
    assert config["d1_databases"][0]["database_id"].startswith("11111111")
    assert config["d1_databases"][0]["database_name"] == "otello-nav"
    assert config["r2_buckets"][0]["bucket_name"] == "otello-source-archive"
    assert config["workers_dev"] is True
    assert "routes" not in config
    assert config["observability"]["enabled"] is True
    assert config["observability"]["head_sampling_rate"] == 1
    assert config["limits"] == {"cpu_ms": 60000, "subrequests": 2000}
    assert config["triggers"]["crons"] == ["*/30 * * * *"]
    assert config["workflows"][0]["class_name"] == "FullRefreshWorkflow"


def test_renderer_uses_custom_domain_without_workers_dev() -> None:
    renderer = _load_renderer()
    config = renderer.render_config(
        _base_config(),
        worker_name="otello-tracker",
        d1_database_id="11111111-2222-3333-4444-555555555555",
        d1_database_name="otello-nav",
        r2_bucket_name="otello-source-archive",
        custom_domain="NAV.Example.com",
    )
    assert config["workers_dev"] is False
    assert config["routes"] == [
        {"pattern": "nav.example.com", "custom_domain": True}
    ]


def test_deploy_workflow_is_guarded_and_runs_remote_preflight() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-cloudflare.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in workflow
    assert "CLOUDFLARE_DEPLOY_ENABLED" in workflow
    assert "environment: production" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert "CLOUDFLARE_ACCOUNT_ID" in workflow
    assert "CLOUDFLARE_D1_DATABASE_ID" in workflow
    assert "render_production_config.py" in workflow
    assert "d1 migrations apply DB --remote" in workflow
    assert "pywrangler deploy --config wrangler.production.jsonc" in workflow
    assert "/api/health" in workflow
    assert "/api/dashboard/summary" in workflow
    assert "summary.get('ready') is True" in workflow


def test_rendered_production_config_is_gitignored() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "cloudflare/wrangler.production.jsonc" in ignore

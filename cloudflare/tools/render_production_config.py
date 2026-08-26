from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "wrangler.jsonc"
DEFAULT_OUTPUT = ROOT / "wrangler.production.jsonc"
WORKER_SUBREQUEST_LIMIT = 50000


def _required(value: str | None, name: str) -> str:
    clean = (value or "").strip()
    if not clean:
        raise ValueError(f"Mangler påkrevd produksjonsverdi: {name}")
    return clean


def render_config(
    base: dict[str, Any],
    *,
    worker_name: str,
    d1_database_id: str,
    d1_database_name: str,
    r2_bucket_name: str,
    custom_domain: str | None = None,
    status_email_to: str | None = None,
    status_email_from: str | None = None,
    public_url: str | None = None,
    deployment_revision: str | None = None,
) -> dict[str, Any]:
    config = json.loads(json.dumps(base))
    config["name"] = _required(worker_name, "worker_name")

    # The one-time ten-year NAV/FX bootstrap is D1-query heavy and the subrequest budget is
    # shared across the entire long-running Workflow invocation, not reset per step.do call.
    # Production exhausted 5,000 requests after checkpointing 2016-2021. Workers Paid allows
    # a substantially higher configured ceiling, so keep 50,000 as a bounded margin that is
    # still far below the platform maximum and leaves room for cleanup/finalization on failure.
    config["limits"] = {
        "cpu_ms": 60000,
        "subrequests": WORKER_SUBREQUEST_LIMIT,
    }

    # Enable Workers Caching only for the default WorkerEntrypoint used by /api/*. Static
    # assets bypass that entrypoint via assets.run_worker_first and remain on the free,
    # automatic Static Assets path instead of inheriting global Worker-cache billing.
    config.pop("cache", None)
    config["exports"] = {
        "default": {
            "type": "worker",
            "cache": {"enabled": True},
        }
    }

    # Keep enough production telemetry to diagnose failures without storing every request
    # or paid trace span. Five percent is intentionally conservative for this low-traffic
    # investor dashboard; real-time tailing remains available when debugging is needed.
    config["observability"] = {
        "enabled": True,
        "logs": {
            "enabled": True,
            "invocation_logs": True,
            "head_sampling_rate": 0.05,
        },
        "traces": {
            "enabled": False,
            "head_sampling_rate": 0,
        },
    }

    databases = config.get("d1_databases") or []
    if len(databases) != 1 or databases[0].get("binding") != "DB":
        raise ValueError("Forventet nøyaktig én D1-binding kalt DB")
    databases[0]["database_id"] = _required(d1_database_id, "d1_database_id")
    databases[0]["database_name"] = _required(d1_database_name, "d1_database_name")

    buckets = config.get("r2_buckets") or []
    if len(buckets) != 1 or buckets[0].get("binding") != "SOURCE_ARCHIVE":
        raise ValueError("Forventet nøyaktig én R2-binding kalt SOURCE_ARCHIVE")
    buckets[0]["bucket_name"] = _required(r2_bucket_name, "r2_bucket_name")

    domain = (custom_domain or "").strip().lower()
    if domain:
        if "/" in domain or "://" in domain or " " in domain:
            raise ValueError("custom_domain skal være kun hostname, f.eks. nav.example.com")
        config["workers_dev"] = False
        config["routes"] = [{"pattern": domain, "custom_domain": True}]
    else:
        config["workers_dev"] = True
        config.pop("routes", None)

    variables = config.setdefault("vars", {})
    clean_revision = (deployment_revision or "").strip()
    if clean_revision:
        variables["DEPLOYMENT_REVISION"] = clean_revision

    email_to = (status_email_to or "").strip()
    email_from = (status_email_from or "").strip()
    if bool(email_to) != bool(email_from):
        raise ValueError("status_email_to og status_email_from må settes sammen")
    if domain and not email_to:
        raise ValueError(
            "status_email_to og status_email_from er påkrevd for produksjon med custom_domain"
        )
    if domain and not clean_revision:
        raise ValueError("deployment_revision er påkrevd for produksjon med custom_domain")

    if email_to:
        config["send_email"] = [
            {
                "name": "STATUS_EMAIL",
                "destination_address": email_to,
                "allowed_sender_addresses": [email_from],
            }
        ]
        variables["STATUS_EMAIL_TO"] = email_to
        variables["STATUS_EMAIL_FROM"] = email_from
        clean_public_url = (public_url or "").strip().rstrip("/")
        if clean_public_url:
            variables["PUBLIC_URL"] = clean_public_url
    else:
        config.pop("send_email", None)

    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render production Wrangler JSONC")
    parser.add_argument("--base", default=str(DEFAULT_BASE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--worker-name", default=os.getenv("CLOUDFLARE_WORKER_NAME", "otello-tracker"))
    parser.add_argument("--d1-database-id", default=os.getenv("CLOUDFLARE_D1_DATABASE_ID"))
    parser.add_argument("--d1-database-name", default=os.getenv("CLOUDFLARE_D1_DATABASE_NAME", "otello-nav"))
    parser.add_argument("--r2-bucket-name", default=os.getenv("CLOUDFLARE_R2_BUCKET_NAME", "otello-source-archive"))
    parser.add_argument("--custom-domain", default=os.getenv("CLOUDFLARE_CUSTOM_DOMAIN"))
    parser.add_argument("--status-email-to", default=os.getenv("CLOUDFLARE_STATUS_EMAIL_TO"))
    parser.add_argument("--status-email-from", default=os.getenv("CLOUDFLARE_STATUS_EMAIL_FROM"))
    parser.add_argument("--public-url", default=os.getenv("CLOUDFLARE_PUBLIC_URL"))
    parser.add_argument("--deployment-revision", default=os.getenv("OTELLO_DEPLOYMENT_REVISION"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    rendered = render_config(
        base,
        worker_name=args.worker_name,
        d1_database_id=args.d1_database_id,
        d1_database_name=args.d1_database_name,
        r2_bucket_name=args.r2_bucket_name,
        custom_domain=args.custom_domain,
        status_email_to=args.status_email_to,
        status_email_from=args.status_email_from,
        public_url=args.public_url,
        deployment_revision=args.deployment_revision,
    )
    output = Path(args.output)
    output.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

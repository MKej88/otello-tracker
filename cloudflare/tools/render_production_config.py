from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "wrangler.jsonc"
DEFAULT_OUTPUT = ROOT / "wrangler.production.jsonc"


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
) -> dict[str, Any]:
    config = json.loads(json.dumps(base))
    config["name"] = _required(worker_name, "worker_name")

    # Paid-plan capacity is deliberately used for the heavy scheduled/workflow path, but
    # we do not expose Cloudflare's 5-minute/10k-subrequest maxima. Lower per-invocation
    # ceilings bound runaway work and denial-of-wallet scenarios while still leaving ample
    # headroom for PDF parsing, historical refreshes and logical model work.
    config["limits"] = {
        "cpu_ms": 60000,
        "subrequests": 500,
    }

    # Workers Caching removes Worker CPU/D1 work on cache hits. Requests are still counted
    # by Workers pricing, so WAF rate limiting remains the pre-Worker cost guard.
    config["cache"] = {"enabled": True}

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
    )
    output = Path(args.output)
    output.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

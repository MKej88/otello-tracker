from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.d1_bootstrap_package import (  # noqa: E402
    load_manifest_file,
    verify_database,
    write_bootstrap_package,
)
from app.jobs.preflight import run_preflight  # noqa: E402


def _export(args: argparse.Namespace) -> int:
    production_preflight = None
    if args.production:
        production_preflight = run_preflight(
            args.database,
            target_date=args.date,
            check_derived=True,
        )
        if not production_preflight["ready"]:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "reason": "production_preflight_failed",
                        "database": args.database,
                        "blockers": production_preflight["blockers"],
                        "warnings": production_preflight["warnings"],
                    },
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )
            return 2

    manifest = write_bootstrap_package(args.database, args.sql, args.manifest)
    payload = {
        "status": "ok",
        "mode": "production" if args.production else "standard",
        "database": args.database,
        "sql": args.sql,
        "manifest": args.manifest,
        "logical_sha256": manifest["logical_sha256"],
        "row_counts": {
            table: data["row_count"]
            for table, data in manifest["tables"].items()
        },
        "key_metrics": manifest["key_metrics"],
    }
    if production_preflight is not None:
        payload["production_preflight"] = {
            "status": production_preflight["status"],
            "target_date": production_preflight["target_date"],
            "warnings": production_preflight["warnings"],
        }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0


def _verify(args: argparse.Namespace) -> int:
    expected = load_manifest_file(args.manifest)
    result = verify_database(args.database, expected)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export and verify a deterministic SQLite -> Cloudflare D1 bootstrap"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser(
        "export", help="Create portable D1 bootstrap SQL and logical parity manifest"
    )
    export_parser.add_argument("--database", required=True, help="Validated SQLite reference DB")
    export_parser.add_argument("--sql", required=True, help="Output SQL file")
    export_parser.add_argument("--manifest", required=True, help="Output JSON manifest")
    export_parser.add_argument(
        "--production",
        action="store_true",
        help="Require strict production preflight before writing the cutover package",
    )
    export_parser.add_argument(
        "--date",
        default=None,
        help="Production target date (YYYY-MM-DD); defaults to today",
    )
    export_parser.set_defaults(handler=_export)

    verify_parser = subparsers.add_parser(
        "verify", help="Compare a local D1 SQLite database with a bootstrap manifest"
    )
    verify_parser.add_argument(
        "--database",
        required=True,
        help="Local D1 SQLite file or Wrangler D1 state directory",
    )
    verify_parser.add_argument("--manifest", required=True, help="Expected JSON manifest")
    verify_parser.set_defaults(handler=_verify)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()

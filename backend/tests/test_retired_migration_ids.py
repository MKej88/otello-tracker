from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_retired_migration_numbers_are_not_reused() -> None:
    backend_migrations = ROOT / "backend/app/db/migrations"
    cloudflare_migrations = ROOT / "cloudflare/migrations"

    backend_0018 = sorted(path.name for path in backend_migrations.glob("0018_*.sql"))
    cloudflare_0008 = sorted(path.name for path in cloudflare_migrations.glob("0008_*.sql"))

    assert backend_0018 == [], (
        "SQLite migration 0018 is retired after the removed shareholder snapshot feature; "
        "the next new SQLite migration must use 0019 or higher."
    )
    assert cloudflare_0008 == [], (
        "Cloudflare D1 migration 0008 is retired after the removed shareholder snapshot feature; "
        "the next new D1 migration must use 0009 or higher."
    )

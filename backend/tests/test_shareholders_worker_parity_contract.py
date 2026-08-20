from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_shareholder_contract_is_kept_in_reference_and_worker() -> None:
    reference = (ROOT / "backend/app/shareholders.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare/src/shareholders.py").read_text(encoding="utf-8")
    fixture = (ROOT / "cloudflare/tools/build_worker_runtime_fixture.py").read_text(encoding="utf-8")
    generator = (ROOT / "cloudflare/tools/generate_d1_schema.py").read_text(encoding="utf-8")

    for token in (
        "EURONEXT_TOP20_URL",
        '"updated_frequency": "DAILY"',
        '"comparison_ready"',
        '"daily_summary"',
        '"biggest_buyers"',
        '"biggest_sellers"',
        '"new_entries"',
        '"exits"',
    ):
        assert token in reference
        assert token in worker

    assert "reference_shareholders_dashboard" in fixture
    assert '"shareholders": reference_shareholders_dashboard(database_path)' in fixture
    assert 'MIGRATIONS / "0008_shareholder_snapshots.sql"' in generator

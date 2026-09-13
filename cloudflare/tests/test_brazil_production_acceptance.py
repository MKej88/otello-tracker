from pathlib import Path


def test_production_acceptance_checks_brazil_focus_contract() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "deploy-cloudflare.yml"
    ).read_text()

    assert '"$base/api/brazil/dashboard?${q}"' in workflow
    assert "brazil_dashboard.get('ready') is True" in workflow
    assert "focus.get('ready') is True" in workflow
    assert "isinstance(focus.get('values'), dict)" in workflow
    assert "focus_meta.get('current_year')" in workflow
    assert "focus_meta.get('next_year')" in workflow
    assert "::warning::Brazil Focus bruker reserve eller gamle data" in workflow

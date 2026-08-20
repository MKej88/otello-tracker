from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_REF = re.compile(r"\buses:\s*([^\s@]+)@([^\s#]+)")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def test_third_party_github_actions_are_pinned_to_commit_sha() -> None:
    floating: list[str] = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
            match = ACTION_REF.search(line)
            if not match:
                continue
            action, ref = match.groups()
            if action.startswith("./"):
                continue
            if not FULL_SHA.fullmatch(ref):
                floating.append(f"{workflow.relative_to(ROOT)}:{line_number}: {action}@{ref}")

    assert not floating, (
        "Produksjons- og CI-actions skal låses til immutable 40-tegns commit-SHA-er. "
        "Oppdater SHA og behold gjerne versjonen som kommentar. Flytende refs:\n"
        + "\n".join(floating)
    )


def test_dependabot_covers_actions_frontend_and_backend() -> None:
    config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert 'package-ecosystem: "github-actions"' in config
    assert 'package-ecosystem: "npm"' in config
    assert 'directory: "/frontend"' in config
    assert 'package-ecosystem: "pip"' in config
    assert 'directory: "/backend"' in config

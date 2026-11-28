"""Route Bemobi read-only diagnostics without widening production permissions."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

COMMON = {
    ".github/workflows/bemobi-diagnostics.yml",
    "tools/select_bemobi_diagnostics.py",
}
FIVE = {"tools/diagnose_bemobi_five_documents.py"}
ARCHIVE = {"tools/audit_bemobi_translation_archive.py"}
RAD = {"tools/probe_bemobi_cvm_rad.py"}


def select(event: str, choice: str = "", changed: set[str] | None = None) -> dict[str, bool]:
    if event == "workflow_dispatch":
        if choice not in {"fem-dokumenter", "oversettelsesarkiv", "cvm-kilder", "alle"}:
            raise ValueError("Ugyldig kontrollvalg")
        return {
            "five": choice in {"fem-dokumenter", "alle"},
            "archive": choice in {"oversettelsesarkiv", "alle"},
            "rad": choice in {"cvm-kilder", "alle"},
        }
    if event not in {"push", "pull_request"}:
        raise ValueError("Uventet hendelse")
    pr = event == "pull_request"
    if changed is None or changed & COMMON:
        return {"five": True, "archive": True, "rad": pr}
    return {
        "five": bool(changed & (FIVE | ({"backend/tests/test_bemobi_five_document_diagnostic.py"} if pr else set()))),
        "archive": bool(changed & (ARCHIVE | ({"backend/tests/test_bemobi_translation_archive_audit.py"} if pr else set()))),
        "rad": pr and bool(changed & RAD),
    }


def changed_paths(event: str, base: str, head: str) -> set[str] | None:
    # The event supplies commit hashes, never shell commands or arbitrary refs.
    import re

    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) and sha != "0" * 40 for sha in (base, head)):
        return None
    revision = base + ("..." if event == "pull_request" else "..") + head
    try:
        raw = subprocess.check_output(
            ["git", "diff", "--name-only", "-z", "--no-renames", revision, "--"],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return set(os.fsdecode(path) for path in raw.split(b"\0") if path)


def main() -> None:
    event = os.environ["EVENT_NAME"]
    changed = None
    if event != "workflow_dispatch":
        changed = changed_paths(event, os.environ.get("BASE_SHA", ""), os.environ.get("HEAD_SHA", ""))
        if changed is None:
            print("::warning::Endringsgrunnlaget er utilgjengelig; kjører alle relevante lesekontroller.")
    results = select(event, os.environ.get("MANUAL_CHOICE", ""), changed)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        for key, value in results.items():
            output.write(f"{key}={str(value).lower()}\n")


if __name__ == "__main__":
    main()

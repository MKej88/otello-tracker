"""Conservative production-deploy scope, relative to the actually live revision."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SHA = re.compile(r"[0-9a-f]{40}")
# Exact offline-only files; unknown paths always require a deployment.
OFFLINE = frozenset({
    "README.md", "ROADMAP.md", "AGENTS.md",
    "tools/nightly_diagnostic_fallback.py",
    "tools/tests/test_nightly_diagnostic_fallback.py",
    ".github/workflows/cloudflare-workflow-diagnostics.yml",
    ".github/workflows/production-performance.yml",
    "frontend/tools/production-performance.mjs",
    "frontend/tools/performance-diagnostics.mjs",
    "frontend/tools/performance-diagnostics.test.mjs",
    "frontend/tools/performance-screen-state.mjs",
    "frontend/tools/performance-screen-state.test.mjs",
    "frontend/tools/performance-trends.mjs",
    "frontend/tools/performance-trends.test.mjs",
    "frontend/tools/performance-trend-core.mjs",
    "frontend/tools/api-network-phases.mjs",
    "frontend/tools/api-network-phases.test.mjs",
    "frontend/tools/trace-candidates.mjs",
    "frontend/tools/trace-candidates.test.mjs",
    "frontend/tools/cpu-profile-summary.mjs",
    "frontend/tools/cpu-profile-summary.test.mjs",
    "frontend/tools/server-timing.mjs",
    "frontend/tools/server-timing.test.mjs",
})


def offline_only(paths):
    return all(path in OFFLINE or (
        path.startswith("docs/") and path.endswith(".md")
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    ) for path in paths)


def live_revision(public_url, domain):
    parsed = urlsplit(public_url)
    if (parsed.scheme != "https" or not domain
            or parsed.netloc.lower() != domain.strip().lower()
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        return None
    url = public_url.rstrip("/") + "/api/health?deploy_scope=" + str(time.time_ns())
    request = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=15) as response:
        if response.geturl() != url or response.status != 200:
            return None
        payload = json.loads(response.read(65537))
    if not isinstance(payload, dict):
        return None
    revision = payload.get("revision")
    if (payload.get("status") == "ok" and payload.get("service") == "otello-api"
            and payload.get("environment") == "cloudflare"
            and isinstance(revision, str) and SHA.fullmatch(revision)):
        return revision
    return None


def deploy_required(live, target, *, git=subprocess.run):
    if not isinstance(live, str) or not SHA.fullmatch(live) or not SHA.fullmatch(target):
        return True
    try:
        # A missing revision or non-ancestor is not evidence for skipping.
        git(["git", "merge-base", "--is-ancestor", live, target],
            check=True, capture_output=True, timeout=30)
        diff = git(["git", "diff", "--name-only", "--no-renames", "-z", live, target, "--"],
                   check=True, capture_output=True, timeout=30).stdout
        paths = diff.decode("utf-8").split("\0")
        if paths[-1] != "":
            return True
        return not offline_only(paths[:-1])
    except (OSError, ValueError, subprocess.SubprocessError):
        return True


def main():
    required = True
    try:
        revision = live_revision(os.environ.get("CLOUDFLARE_PUBLIC_URL", ""),
                                 os.environ.get("CLOUDFLARE_CUSTOM_DOMAIN", ""))
        required = deploy_required(revision, os.environ["GITHUB_SHA"])
    except Exception:
        # No credentials or raw HTTP errors in output. Uncertainty means deploy.
        print("Aktiv produksjonsrevisjon kunne ikke bekreftes; behold ordinær utrulling.")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
        handle.write(f"required={'true' if required else 'false'}\n")
    print("Produksjonsutrulling nødvendig: " + str(required))


if __name__ == "__main__":
    main()

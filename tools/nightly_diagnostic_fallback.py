"""Decide whether a watchdog should run the missing full daily diagnosis."""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, time, timedelta
from urllib.request import Request, urlopen


def fallback_needed(now, body):
    current = now.astimezone(UTC)
    # Same 03:35 + 55-minute deadline as production_monitor.expected_nightly_date.
    if current.time() < time(4, 30):
        return False
    target = (current.date()-timedelta(days=1)).isoformat()
    date = re.search(r"(?m)^- Datadato: `(\d{4}-\d{2}-\d{2})`$", body)
    if not date or date.group(1) != target:
        return True
    # A previously failed or incomplete diagnosis is worth checking again.
    return ("| GitHub Actions – diagnose | success |" not in body
            or "| Fulloppdatering (D1) | SUCCESS |" not in body
            or "| Workflow-instans | complete |" not in body
            or "**AVVIK**" in body)


def main():
    now=datetime.now(UTC)
    needed=False
    if now.time() >= time(4,30):
        repo=os.environ["GITHUB_REPOSITORY"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo):
            raise ValueError("Ugyldig repository")
        try:
            req=Request("https://api.github.com/repos/"+repo+"/issues/164",headers={
                "Authorization":"Bearer "+os.environ["GH_TOKEN"],
                "Accept":"application/vnd.github+json"})
            with urlopen(req,timeout=20) as resp:
                raw=resp.read(1024*1024+1)
                if len(raw)>1024*1024:
                    raise ValueError("Statusrapport for stor")
                issue=json.loads(raw)
            needed=fallback_needed(now,str(issue.get("body") or ""))
        except Exception:
            # Fail safe to a read-only full diagnosis, not an assumed healthy result.
            needed=True
            print("Kunne ikke lese statusrapport; utfører reservekontroll.")
    with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as out:
        out.write(f"needed={'true' if needed else 'false'}\n")
    print("Reservekontroll nødvendig: "+str(needed))


if __name__=="__main__":
    main()

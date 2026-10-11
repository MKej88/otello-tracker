#!/usr/bin/env python3
"""Check committed Python SHA-256 locks and npm lockfile integrity, offline."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_INPUTS = {
    "backend/requirements.lock.txt": "backend/requirements.txt",
    "backend/requirements-dev.lock.txt": "backend/requirements-dev.txt",
    "cloudflare/worker-tooling.lock.txt": "cloudflare/worker-tooling.in",
}
PIN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;]+)")
LOCK_PIN = re.compile(r"(?m)^([A-Za-z0-9_.-]+)==([^\s\\]+)")
HASH = re.compile(r"--hash=sha256:[a-f0-9]{64}\b")


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_pins(relative: str, seen: set[str] | None = None) -> dict[str, str]:
    seen = seen if seen is not None else set()
    if relative in seen:
        raise ValueError(f"Cyclic requirements inclusion: {relative}")
    seen.add(relative)
    path = ROOT / relative
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith("-r "):
            child = (path.parent / value[3:].strip()).relative_to(ROOT).as_posix()
            pins.update(declared_pins(child, seen))
            continue
        match = PIN.fullmatch(value)
        if not match:
            raise ValueError(f"{relative}: not an exact pin: {value}")
        pins[normalized(match[1])] = match[2]
    seen.remove(relative)
    return pins


def check_python() -> None:
    for locked, source in LOCK_INPUTS.items():
        body = (ROOT / locked).read_text(encoding="utf-8")
        entries = list(LOCK_PIN.finditer(body))
        if not entries:
            raise ValueError(f"{locked}: no pinned packages")
        found: dict[str, str] = {}
        for index, entry in enumerate(entries):
            package, version = normalized(entry[1]), entry[2]
            if package in found:
                raise ValueError(f"{locked}: duplicate package {package}")
            found[package] = version
            end = entries[index + 1].start() if index + 1 < len(entries) else len(body)
            if not HASH.search(body[entry.end():end]):
                raise ValueError(f"{locked}: missing SHA-256 hash for {package}")
        for package, version in declared_pins(source).items():
            if found.get(package) != version:
                raise ValueError(
                    f"{locked}: {package} must match {source} ({version}); "
                    "regenerate the hash lock before merging"
                )
        print(f"{locked}: {len(found)} locked packages with SHA-256 hashes")


def check_npm() -> None:
    manifest = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    if lock.get("lockfileVersion") != 3:
        raise ValueError("frontend/package-lock.json must use lockfileVersion 3")
    for kind in ("dependencies", "devDependencies", "optionalDependencies"):
        if manifest.get(kind, {}) != lock["packages"][""].get(kind, {}):
            raise ValueError(f"frontend/package-lock.json: {kind} differs from package.json")
    count = 0
    for name, package in lock["packages"].items():
        if not name or not package.get("resolved"):
            continue
        integrity = package.get("integrity", "")
        if not re.fullmatch(r"sha(256|384|512)-[A-Za-z0-9+/]+={0,2}", integrity):
            raise ValueError(f"frontend/package-lock.json: {name} has no SRI digest")
        count += 1
    print(f"frontend/package-lock.json: {count} packages with npm integrity hashes")


if __name__ == "__main__":
    try:
        check_python()
        check_npm()
    except (ValueError, KeyError, FileNotFoundError) as error:
        print(f"Dependency integrity check FAILED: {error}", file=sys.stderr)
        sys.exit(1)

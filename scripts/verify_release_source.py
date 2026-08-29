"""Reject dirty, generated, incomplete, or stale release source."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


FORBIDDEN_PARTS = {".git", ".next", "node_modules", "__pycache__", ".pytest_cache", ".venv"}
REQUIRED = {
    "DEPLOYMENT.md",
    "backend/Dockerfile",
    "backend/alembic.ini",
    "backend/app/main.py",
    "backend/scripts/benchmark_release_search.py",
    "frontend/Dockerfile",
    "frontend/next.config.js",
    "frontend/package-lock.json",
    "frontend/scripts/check-search-window.mjs",
    "deploy/slotctl.py",
    "deploy/production-base.json",
    "scripts/compare_performance.py",
    "scripts/release_retention.py",
}


def output(*command: str, cwd: Path) -> str:
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--expected-base-release", required=True)
    parser.add_argument("--expected-base-manifest", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    status = output("git", "status", "--porcelain", cwd=root)
    if status:
        raise SystemExit("Release source must be a clean Git worktree")
    tracked = output("git", "ls-files", cwd=root).splitlines()
    forbidden = [path for path in tracked if FORBIDDEN_PARTS.intersection(Path(path).parts)]
    if forbidden:
        raise SystemExit(f"Generated/dependency paths are tracked: {forbidden[:10]}")
    missing = sorted(path for path in REQUIRED if not (root / path).is_file())
    if missing:
        raise SystemExit(f"Required release files are missing: {missing}")
    base = json.loads((root / "deploy/production-base.json").read_text(encoding="utf-8"))
    expected = {
        "release": args.expected_base_release,
        "source_manifest_sha256": args.expected_base_manifest,
    }
    for key, value in expected.items():
        if base.get(key) != value:
            raise SystemExit(f"Production base {key} mismatch: {base.get(key)!r} != {value!r}")
    payload = {
        "commit": output("git", "rev-parse", "HEAD", cwd=root),
        "tracked_files": len(tracked),
        "base_release": base["release"],
        "base_manifest": base["source_manifest_sha256"],
        "lock_sha256": digest(root / "frontend/package-lock.json"),
        "requirements_sha256": digest(root / "backend/requirements.txt"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

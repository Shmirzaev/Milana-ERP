"""Create a deterministic source archive and manifest from a clean Git commit."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path


ROOTS = ("backend/", "frontend/", "connectors/", "docs/", "deploy/", "scripts/")
ROOT_FILES = {"DEPLOYMENT.md", "pyproject.toml"}
FORBIDDEN = {".git", ".next", "node_modules", "__pycache__", ".pytest_cache", ".venv"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True).stdout:
        raise SystemExit("Release packaging requires a clean Git worktree")
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.splitlines()
    selected = sorted(
        path for path in tracked
        if (path in ROOT_FILES or path.startswith(ROOTS))
        and not FORBIDDEN.intersection(Path(path).parts)
        and (root / path).is_file()
    )
    if len(selected) < 650:
        raise SystemExit(f"Release source is unexpectedly small: {len(selected)} files")
    manifest = "".join(
        f"{sha256_bytes((root / path).read_bytes())}  {path}\n" for path in selected
    ).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for path in selected:
                    data = (root / path).read_bytes()
                    info = tarfile.TarInfo(path)
                    info.size = len(data)
                    info.mode = 0o755 if path.endswith((".sh", "slotctl.py")) else 0o644
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(data))
                info = tarfile.TarInfo("SOURCE_MANIFEST.sha256")
                info.size = len(manifest)
                info.mode = 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(manifest))
    archive_hash = hashlib.sha256(args.output.read_bytes()).hexdigest()
    metadata = {
        "release": args.release,
        "source_files": len(selected),
        "source_manifest_sha256": sha256_bytes(manifest),
        "archive_sha256": archive_hash,
        "archive_bytes": args.output.stat().st_size,
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip(),
    }
    metadata_path = args.output.with_suffix(args.output.suffix + ".json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

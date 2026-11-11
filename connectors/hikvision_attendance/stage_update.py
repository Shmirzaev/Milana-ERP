"""Prepare a source-only update; never modify an installed attendance reader.

Configuration, certificate pins, DPAPI secrets, cursors and scheduled-task wrappers
are deliberately excluded. Activation remains a separate deployment operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


UPDATE_FILES = ("read_only_connector.py", "run_scheduled.ps1", "requirements.txt", "README.md")


def stage_update(destination: Path, source: Path | None = None) -> dict:
    source = (source or Path(__file__).resolve().parent).resolve(strict=True)
    # Read and validate the complete source set before creating any output.
    payloads = {}
    for name in UPDATE_FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Update source must be a regular file: {name}")
        payloads[name] = path.read_bytes()
    # An existing directory may be the live installation. Never accept it,
    # even when empty, and never offer a force/overwrite option.
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "hikvision-attendance-read-only-update", "version": 1, "files": {}}
    for name, content in payloads.items():
        with (destination / name).open("xb") as output:
            output.write(content)
        manifest["files"][name] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    with (destination / "UPDATE_MANIFEST.json").open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New, nonexistent staging directory")
    args = parser.parse_args()
    manifest = stage_update(args.destination)
    print(json.dumps({"destination": str(args.destination.resolve()), "files": list(manifest["files"])}))


if __name__ == "__main__":
    main()

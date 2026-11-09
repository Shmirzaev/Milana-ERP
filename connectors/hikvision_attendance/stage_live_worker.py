"""Stage separate writer source. Never installs, configures, schedules or connects."""
import argparse
import hashlib
import json
from pathlib import Path

FILES = ("live_device.py", "live_worker.py", "requirements-live.txt", "live-config.example.json", "README_LIVE.md")


def stage(destination: Path, source: Path | None = None) -> dict:
    source = (source or Path(__file__).resolve().parent).resolve(strict=True)
    payloads = {}
    for name in FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Writer source must be a regular file: " + name)
        payloads[name] = path.read_bytes()
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "hikvision-separate-writer-source", "version": 1, "activated": False, "files": {}}
    for name, body in payloads.items():
        with (destination / name).open("xb") as output: output.write(body)
        manifest["files"][name] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    with (destination / "WRITER_MANIFEST.json").open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2); output.write("\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    stage(args.destination)
    print("Separate writer source staged; nothing installed or activated.")

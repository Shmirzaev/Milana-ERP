"""Emit an immutable deployment manifest from the exact CI artifact/image pair."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
from release_manifest import REPOSITORY, fingerprint, validate  # noqa: E402


def main():
    release = os.environ["RELEASE_ID"]
    metadata = json.loads(Path(f"milana-erp-{release}.tar.gz.json").read_text())
    if metadata["git_commit"] != os.environ["GITHUB_SHA"]:
        raise ValueError("Artifact source differs from validated source")
    plan = validate({
        "version": 1, "repository": REPOSITORY, "release": release,
        "commit": metadata["git_commit"], "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
        "base": json.loads(Path("deploy/production-base.json").read_text()),
        "archive_sha256": metadata["archive_sha256"],
        "source_manifest_sha256": metadata["source_manifest_sha256"],
        "schema_fingerprint": fingerprint(Path.cwd()),
        "images": {role: os.environ[f"{role.upper()}_IMAGE"] for role in ("backend", "frontend")},
    })
    Path("deployment.json").write_text(json.dumps(plan, indent=2) + "\n")


if __name__ == "__main__":
    main()

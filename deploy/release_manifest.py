"""The data-only contract shared by CI and the installed deployment worker."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPOSITORY = "Shmirzaev/Milana-ERP"
BRANCH = "clone_main"
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
RELEASE = re.compile(r"[0-9]{8}_[0-9]{6}(?:_[1-9][0-9]{0,19}_[1-9][0-9]{0,5})?")
CI_POLICY_PATHS = (
    ".github/workflows/ci.yml", ".github/workflows/security-scan.yml",
    "scripts/security_gate.py", "security/accepted-findings.json",
    "scripts/package_release.py", "scripts/verify_release_source.py",
    "scripts/prepare_release_manifest.py", "scripts/release_ci_identity.py",
    "scripts/run_backend_regression_shard.py",
)


def fingerprint(root: Path) -> str:
    """Any migration edit requires the reviewed migration/recovery procedure."""
    files = sorted((root / "backend/alembic/versions").glob("*.py"))
    if not files:
        raise ValueError("Migration history is missing")
    return hashlib.sha256(b"".join(
        p.name.encode() + b"\0" + p.read_bytes() + b"\0" for p in files
    )).hexdigest()


def validate(plan: dict) -> dict:
    if plan.get("version") != 1 or plan.get("repository") != REPOSITORY:
        raise ValueError("Unexpected deployment manifest/repository")
    if not RELEASE.fullmatch(str(plan.get("release", ""))):
        raise ValueError("Invalid release ID")
    for key in ("commit", "tree"):
        if not HEX40.fullmatch(str(plan.get(key, ""))):
            raise ValueError(f"Invalid {key}")
    for key in ("archive_sha256", "source_manifest_sha256", "schema_fingerprint"):
        if not HEX64.fullmatch(str(plan.get(key, ""))):
            raise ValueError(f"Invalid {key}")
    base = plan.get("base", {})
    if not RELEASE.fullmatch(str(base.get("release", ""))) or not HEX64.fullmatch(
        str(base.get("source_manifest_sha256", ""))
    ):
        raise ValueError("Invalid production baseline")
    if not HEX40.fullmatch(str(base.get("git_baseline_commit", ""))):
        raise ValueError("Invalid baseline commit")
    if not re.fullmatch(r"[0-9A-Za-z_]+", str(base.get("database_revision", ""))):
        raise ValueError("Invalid database revision")
    if not isinstance(plan.get("run_id"), int) or plan["run_id"] <= 0:
        raise ValueError("Invalid build run")
    for role in ("backend", "frontend"):
        image = str(plan.get("images", {}).get(role, ""))
        prefix = f"ghcr.io/shmirzaev/milana-erp-{role}@sha256:"
        if not image.startswith(prefix) or not HEX64.fullmatch(image[len(prefix):]):
            raise ValueError("Only pinned Milana image digests are deployable")
    return plan


def identity(plan: dict) -> str:
    return hashlib.sha256(json.dumps(validate(plan), sort_keys=True).encode()).hexdigest()

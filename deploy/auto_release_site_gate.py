#!/usr/bin/env python3
"""Installed site QA adapter. All probes are read-only; missing evidence refuses promotion."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.request
import uuid
from urllib.parse import unquote, urlsplit

from auto_release_host import BASE, CONFIG, STATE, atomic, assert_container, assert_runtime, command, inspect, trusted
from release_manifest import identity, validate


KINDS = {"browser", "permissions", "persisted_results", "adjacent_workflows"}


@contextlib.contextmanager
def exported_snapshot():
    settings = {}
    for line in (BASE / "shared/backend.env").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values = shlex.split(value)
            if values:
                settings[key.strip()] = values[0]
    url = urlsplit(settings["DATABASE_URL"].replace("postgresql+psycopg2:", "postgresql:"))
    args = ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "--no-password", "--host", url.hostname,
            "--port", str(url.port or 5432), "--username", unquote(url.username or ""),
            "--dbname", unquote(url.path.lstrip("/"))]
    keeper = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env={**os.environ, "PGPASSWORD": unquote(url.password or ""), "PGCONNECT_TIMEOUT": "10"})
    try:
        keeper.stdin.write(b"BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSELECT pg_export_snapshot();\n")
        keeper.stdin.flush()
        snapshot = keeper.stdout.readline().decode().strip()
        if not re.fullmatch(r"[0-9A-F]+-[0-9A-F]+-[0-9]+", snapshot):
            raise ValueError("Unable to export a stable read-only database snapshot")
        yield snapshot
    finally:
        try:
            keeper.communicate(b"ROLLBACK;\n\\q\n", timeout=10)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            keeper.kill()
            keeper.wait()


def run_probe(image, probe, arguments):
    name = "milana-auto-probe-" + uuid.uuid4().hex
    try:
        return json.loads(command(
        ["docker", "run", "--name", name, "--rm", "-i", "--network", "host", "--read-only",
         "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "1024m",
         "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
         "-v", "/app/storage:/app/storage:ro",
         "--env-file", str(BASE / "shared/backend.env"),
         "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONPATH=/app:/app/backend",
         "-e", "SHARED_STORE_URL=sqlite:////tmp/qa-counters.db",
         "--entrypoint", "python", image, "-", json.dumps(arguments)],
        input=probe.read_bytes(), stdout=subprocess.PIPE, timeout=600))
    finally:
        # Killing the Docker CLI alone does not stop its container after a timeout.
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30, check=False)


def source_files(root):
    return {name: digest for digest, name in
            (line.split("  ", 1) for line in (root / "SOURCE_MANIFEST.sha256").read_text().splitlines())}


def changed_application_paths(before, after):
    return sorted(path for path in before.keys() | after.keys()
                  if path.startswith(("backend/", "frontend/", "connectors/")) and before.get(path) != after.get(path))


def evidence_file(reference, folder):
    path = Path(reference["path"])
    if path.is_symlink() or not path.is_relative_to(folder) or path.resolve() != path:
        raise ValueError("QA evidence escaped its protected directory")
    trusted(path, reference["sha256"])
    return path


def application_approval(plan, changes, folder):
    if not changes:
        return {"application_changed": False}
    path = folder / (plan["commit"] + ".json")
    trusted(path)
    approval = json.loads(path.read_text())
    if (approval.get("identity") != identity(plan) or approval.get("changed_paths") != changes
            or not approval.get("reviewed_by") or not isinstance(approval.get("checked_at"), (int, float))
            or not 0 <= time.time() - approval["checked_at"] <= 10800
            or set(approval.get("evidence", {})) != KINDS):
        raise ValueError("Missing current exact-plan workflow approval")
    for kind, reference in approval["evidence"].items():
        artifact = json.loads(evidence_file(reference, folder).read_text())
        checks = artifact.get("checks")
        if (artifact.get("identity") != identity(plan) or artifact.get("kind") != kind
                or not isinstance(checks, list) or not checks
                or any(not c.get("name") or "actual" not in c or "expected" not in c
                       or c["actual"] != c["expected"] for c in checks)
                or not any(not isinstance(c["actual"], bool) for c in checks)):
            raise ValueError("Workflow evidence lacks verifiable observed results")
        if kind == "browser":
            if artifact.get("console_errors") != 0 or not artifact.get("screenshots"):
                raise ValueError("Browser QA screenshot/console evidence is missing")
            for screenshot in artifact["screenshots"]:
                if not evidence_file(screenshot, folder).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("Browser QA screenshot is invalid")
    return {"application_changed": True, "approval_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def runtime_check(container, *, backend):
    image = inspect("image", container["Image"])
    (assert_runtime if backend else assert_container)(container, image)
    # Docker sends stderr log frames to the CLI's stderr; inspect both streams.
    result = subprocess.run(["docker", "logs", "--since", "5m", container["Id"]], capture_output=True)
    if result.returncode or re.search(rb"Traceback|\bCRITICAL\b|\bException\b|\" 5\d\d\b", result.stdout + result.stderr):
        raise ValueError("Recent application error logs require inspection")
    if backend:
        processes = command(["docker", "top", container["Id"], "-eo", "args"], stdout=subprocess.PIPE)
        workers = sum(b"multiprocessing.spawn" in line and b"spawn_main" in line for line in processes.splitlines())
        if workers != 2:
            raise ValueError("Backend must have exactly two application workers")


def main():
    phase = sys.argv[1]
    if phase not in {"prepare", "postflight", "closing"}:
        raise ValueError("Unknown site QA phase")
    request = json.loads(sys.stdin.buffer.read(65537))
    plan, host = validate(request["plan"]), request["host"]
    trusted(CONFIG)
    config = json.loads(CONFIG.read_text())
    if host["role"] != config["role"]:
        raise ValueError("Host role mismatch")
    before_root = BASE / "releases" / plan["base"]["release"]
    candidate_root = BASE / "releases" / plan["release"]
    changes = changed_application_paths(source_files(before_root), source_files(candidate_root))
    approval = application_approval(plan, changes, BASE / "shared/qa-approvals")
    journal = json.loads((STATE / (plan["release"] + ".json")).read_text())
    if journal["identity"] != identity(plan):
        raise ValueError("Site gate journal identity mismatch")
    role = config["role"]
    slot = host["candidate_slot"] if phase == "prepare" else host["slot"]
    before_slot = journal["before"]["slot"]
    candidate = inspect("container", f"milana-{role}-{slot}")
    baseline = inspect("container", f"milana-{role}-{before_slot}")
    runtime_check(candidate, backend=role == "backend")
    runtime_check(baseline, backend=role == "backend")
    receipt = {"phase": phase, "identity": identity(plan), "approval": approval}
    if role == "backend":
        probe = Path(config["probe"])
        trusted(probe, config["probe_sha256"])
        ports = {"blue": 18001, "green": 18002}
        arguments = {"baseline": f"http://127.0.0.1:{ports[before_slot]}",
                     "candidate": f"http://127.0.0.1:{ports[slot]}",
                     "database_revision": plan["base"]["database_revision"]}
        with exported_snapshot() as snapshot:
            frozen = {**arguments, "mode": "facts", "snapshot": snapshot}
            before = run_probe(baseline["Image"], probe, frozen)
            after = run_probe(candidate["Image"], probe, frozen)
            if before != after:
                raise ValueError("Complete ordered API facts differ on the same database snapshot")
            receipt["frozen_facts"] = before
        receipt["api_and_database"] = run_probe(baseline["Image"], probe, arguments)
    else:
        ports = {"blue": 13001, "green": 13002}
        for port in {ports[before_slot], ports[slot]}:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=15) as response:
                if response.status != 200 or len(response.read()) < 1000:
                    raise ValueError("Frontend login page contract failed")
    folder = STATE / "site-evidence"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = folder / f"{plan['release']}-{phase}-{time.time_ns()}.json"
    atomic(target, receipt)
    target.chmod(0o600)
    print(json.dumps({"passed": True, "identity": identity(plan)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"passed": False, "error": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None

#!/usr/bin/env python3
"""Installed, root-owned host operations. Never execute code from a CI archive.

One JSON request is read on stdin; only a sanitized receipt is written on stdout.
Install beside release_manifest.py. Configuration and hooks are root-owned.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from urllib.parse import unquote, urlsplit

from release_manifest import fingerprint, identity, validate

BASE = Path("/opt/milana-erp")
CONFIG = Path("/etc/milana-auto-release/host.json")
STATE = BASE / "runtime/auto-release"
INBOX = Path("/var/lib/milana-auto-release/inbox")
MAX_ARCHIVE = 128 * 1024 * 1024


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def trusted(path, expected=None):
    if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise ValueError("Deployment configuration/code must be root-owned and non-writable")
    if expected and sha(path) != expected:
        raise ValueError("Installed deployment tool changed; review and repin it")


def command(args, **kwargs):
    # Raw subprocess errors can contain environment/connection details. Do not log them.
    result = subprocess.run(args, stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        raise RuntimeError(f"Deployment command failed: {args[0]} (exit {result.returncode})")
    return result.stdout


def inspect(kind, name):
    return json.loads(command(["docker", kind, "inspect", name], stdout=subprocess.PIPE))[0]


def verify_manifest(root, expected):
    manifest = root / "SOURCE_MANIFEST.sha256"
    if sha(manifest) != expected:
        raise ValueError("Source manifest drift")
    for line in manifest.read_text().splitlines():
        digest, name = line.split("  ", 1)
        path = safe_path(name)
        target = root.joinpath(*path.parts)
        if target.is_symlink() or sha(target) != digest:
            raise ValueError("Source file drift")


def safe_path(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or path.is_absolute() or ".." in path.parts
            or str(path) != name or ":" in name):
        raise ValueError("Unsafe archive path")
    if path.parts[0] not in {"backend", "frontend", "connectors", "docs", "deploy", "scripts",
                             ".dockerignore", "DEPLOYMENT.md", "pyproject.toml", "SOURCE_MANIFEST.sha256"}:
        raise ValueError("Unexpected source root")
    if any(part.startswith(".env") or part in {".git", "node_modules", ".venv"} for part in path.parts):
        raise ValueError("Forbidden source file")
    return path


def extract_archive(archive, destination, plan):
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError("Archive too large")
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != plan["archive_sha256"]:
        raise ValueError("Archive digest mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as source:
        entries = source.getmembers()
        if sum(entry.size for entry in entries) > MAX_ARCHIVE * 4:
            raise ValueError("Expanded archive too large")
        names = set()
        for entry in entries:
            safe_path(entry.name)
            if not entry.isfile() or entry.name in names:
                raise ValueError("Only unique regular source files are allowed")
            names.add(entry.name)
        destination.mkdir(mode=0o755)
        for entry in entries:
            target = destination / entry.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                shutil.copyfileobj(source.extractfile(entry), stream)
            target.chmod(0o644)
    verify_manifest(destination, plan["source_manifest_sha256"])
    actual = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
    declared = {line.split("  ", 1)[1] for line in (destination / "SOURCE_MANIFEST.sha256").read_text().splitlines()}
    if actual != declared | {"SOURCE_MANIFEST.sha256"}:
        raise ValueError("Archive has files outside its manifest")


def assert_container(container, image):
    if container["Image"] != image["Id"]:
        raise ValueError("Container image mismatch")
    if any(container["Config"].get(key) != image["Config"].get(key) for key in ("Cmd", "Entrypoint")):
        raise ValueError("Image default command was overridden")
    if container["RestartCount"] or container["State"].get("OOMKilled") or not container["State"]["Running"]:
        raise ValueError("Container is not healthy")


def assert_runtime(container, image):
    assert_container(container, image)
    env = dict(value.split("=", 1) for value in container["Config"]["Env"] if "=" in value)
    if env.get("ENV", "").lower() != "production":
        raise ValueError("Backend must use strict production settings")
    for key in ("RUN_SEED_ON_STARTUP", "STARTUP_SCHEMA_SYNC", "SEED_DEMO_USERS", "SEED_SAMPLE_DATA"):
        if env.get(key, "false").lower() not in {"false", "0", ""}:
            raise ValueError("Startup writes must be disabled")


def reported_release(url, expected):
    with urllib.request.urlopen(url, timeout=10) as response:
        if response.status != 200 or json.load(response).get("release") != expected:
            raise ValueError("Backend reports a different release")


class Host:
    def __init__(self, config):
        self.config = config
        self.role = config["role"]
        if self.role not in {"backend", "frontend"}:
            raise ValueError("Invalid installed host role")
        controller = Path(config["controller"])
        trusted(controller, config["controller_sha256"])
        spec = importlib.util.spec_from_file_location("installed_slotctl", controller)
        self.ctl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ctl)
        # Python redirect_stdout does not capture child process file descriptors.
        # All installed-controller subprocess output must stay out of our JSON protocol.
        def captured_run(*args, capture=False):
            output = command(list(args), stdout=subprocess.PIPE).decode().strip()
            return output if capture else ""
        self.ctl.run = captured_run

    def snapshot(self):
        state = self.ctl.read_state()
        if state.get("role") != self.role or state.get("active_slot") not in {"blue", "green"}:
            raise ValueError("Unexpected runtime slot state")
        root = (BASE / "current").resolve(strict=True)
        if root != BASE / "releases" / state["active_release"]:
            raise ValueError("Slot and source pointer disagree")
        manifest = sha(root / "SOURCE_MANIFEST.sha256")
        verify_manifest(root, manifest)
        container = inspect("container", self.ctl.container_name(self.role, state["active_slot"]))
        if container["Config"]["Labels"].get("milana.release") != state["active_release"]:
            raise ValueError("Container release and slot state disagree")
        proxy = self.ctl.PROXY_PATH.read_text()
        port = self.ctl.slot_port(self.role, state["active_slot"])
        if f"server active 127.0.0.1:{port} " not in proxy:
            raise ValueError("Actual proxy routing disagrees with slot state")
        command(["systemctl", "is-active", "--quiet", "milana-router"])
        if self.role == "backend":
            assert_runtime(container, inspect("image", container["Image"]))
            # Reads the real Alembic head; never stamps or runs migrations.
            command(["docker", "exec", "-e", "PYTHONPATH=/app:/app/backend", container["Id"],
                     "python", "-c", "from app.main import _verify_alembic_current; _verify_alembic_current()"],
                    stdout=subprocess.PIPE)
        else:
            assert_container(container, inspect("image", container["Image"]))
        return {"role": self.role, "release": state["active_release"], "slot": state["active_slot"],
                "source_manifest_sha256": manifest, "container": container["Id"],
                "schema_fingerprint": fingerprint(root)}

    def baseline(self, plan):
        actual = self.snapshot()
        for key in ("release", "source_manifest_sha256"):
            if actual[key] != plan["base"][key]:
                raise ValueError("Production baseline changed")
        if actual["schema_fingerprint"] != plan["schema_fingerprint"]:
            raise ValueError("Migration changes require the reviewed recovery procedure")
        return actual

    def gate(self, phase, plan, snapshot):
        # Site-specific signed-in workflow QA, full-fact/performance/database checks.
        # Missing or changed hooks stop automation, rather than claiming health is QA.
        hook = Path(self.config["gate"])
        trusted(hook, self.config["gate_sha256"])
        receipt = json.loads(command([str(hook), phase], input=json.dumps(
            {"plan": plan, "host": snapshot}).encode(), stdout=subprocess.PIPE))
        if receipt.get("passed") is not True or receipt.get("identity") != identity(plan):
            raise ValueError("Deployment gate rejected the exact candidate")
        return receipt

    def backup(self, plan):
        folder = BASE / "shared/backups"
        folder.mkdir(parents=True, exist_ok=True)
        dump = folder / f"auto_pre_{plan['release']}.dump"
        # Parse values without evaluating shell expansions or exposing DATABASE_URL.
        settings = {}
        for line in (BASE / "shared/backend.env").read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                words = shlex.split(value)
                if words:
                    settings[key.strip()] = words[0]
        url = urlsplit(settings["DATABASE_URL"].replace("postgresql+psycopg2:", "postgresql:"))
        env = {**os.environ, "PGPASSWORD": unquote(url.password or "")}
        args = ["pg_dump", "--format=custom", "--no-password", "--host", url.hostname,
                "--port", str(url.port or 5432), "--username", unquote(url.username or ""),
                "--dbname", unquote(url.path.lstrip("/"))]
        fd = os.open(dump, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            command(args, env=env, stdout=stream)
            stream.flush()
            os.fsync(stream.fileno())
        listing = command(["pg_restore", "--list", str(dump)], stdout=subprocess.PIPE)
        objects = sum(bool(line.strip()) and not line.startswith(b";") for line in listing.splitlines())
        if not dump.stat().st_size or objects <= 100:
            raise ValueError("Backup validation failed")
        listing_path = dump.with_suffix(".restore-list")
        with listing_path.open("xb") as stream:
            os.chmod(listing_path, 0o600)
            stream.write(listing)
        return {"path": str(dump), "bytes": dump.stat().st_size, "sha256": sha(dump),
                "restore_objects": objects, "restore_list_sha256": sha(listing_path)}

    def record(self, plan):
        return STATE / f"{plan['release']}.json"

    def reservation(self, plan, *, required=True):
        path = STATE / "reservation.json"
        expected = {"release": plan["release"], "identity": identity(plan)}
        if not path.exists():
            if required:
                raise ValueError("Deployment reservation is missing")
            return
        if json.loads(path.read_text()) != expected:
            raise ValueError("Another candidate owns the deployment reservation")

    def release_reservation(self, plan):
        path = STATE / "reservation.json"
        if path.exists() and json.loads(path.read_text()) == {
            "release": plan["release"], "identity": identity(plan)
        }:
            path.unlink()

    def point_current(self, release):
        # A unique root-owned directory makes retry after a crash safe.
        with tempfile.TemporaryDirectory(prefix=".auto-current-", dir=BASE) as temporary:
            link = Path(temporary) / "current"
            link.symlink_to(BASE / "releases" / release, target_is_directory=True)
            os.replace(link, BASE / "current")

    def prepare(self, plan):
        if self.record(plan).exists():
            raise ValueError("Release already attempted; preserve evidence and use a new release ID")
        before = self.baseline(plan)
        reserved = STATE / "reservation.json"
        if reserved.exists():
            raise ValueError("A prepared deployment is reserved; finish or explicitly cancel it")
        if shutil.disk_usage(BASE).used / shutil.disk_usage(BASE).total >= .80:
            raise ValueError("Disk use is at or above 80%; run protected retention first")
        journal = {"identity": identity(plan), "plan": plan, "before": before, "phase": "preparing"}
        atomic(self.record(plan), journal)
        atomic(reserved, {"release": plan["release"], "identity": identity(plan)})
        destination = BASE / "releases" / plan["release"]
        extract_archive(INBOX / f"{plan['release']}.tar.gz", destination, plan)
        command(["docker", "pull", plan["images"][self.role]], stdout=subprocess.PIPE)
        image = inspect("image", plan["images"][self.role])
        if image["Config"].get("Labels", {}).get("org.opencontainers.image.revision") != plan["commit"]:
            raise ValueError("Image source revision differs from validated commit")
        # No migration is run: an identical migration history is mandatory above.
        if self.role == "backend":
            journal["backup"] = self.backup(plan)
            # Refuse unsafe shared startup settings BEFORE starting a container.
            shared = (BASE / "shared/backend.env").read_text()
            for line in shared.splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    if key.strip() in {"RUN_SEED_ON_STARTUP", "STARTUP_SCHEMA_SYNC"}:
                        if value.strip().strip("\"'").lower() not in {"false", "0", ""}:
                            raise ValueError("Shared environment enables startup writes")
        slot = "green" if before["slot"] == "blue" else "blue"
        journal["slot"] = slot
        atomic(self.record(plan), journal)
        self.ctl.stage(self.role, slot, plan["release"], plan["images"][self.role])
        candidate = inspect("container", self.ctl.container_name(self.role, slot))
        assert_container(candidate, image)
        if self.role == "backend":
            assert_runtime(candidate, image)
            reported_release(f"http://127.0.0.1:{self.ctl.slot_port(self.role, slot)}/ready", plan["release"])
        journal["candidate"] = candidate["Id"]
        journal["gate"] = self.gate("prepare", plan, {**before, "candidate_slot": slot})
        journal["phase"] = "ready"
        journal["ready_at"] = time.time()
        atomic(self.record(plan), journal)
        return journal

    def ready(self, plan):
        self.reservation(plan)
        journal = json.loads(self.record(plan).read_text())
        if journal["identity"] != identity(plan) or journal["phase"] != "ready":
            raise ValueError("Candidate is not prepared")
        if time.time() - journal["ready_at"] > self.config.get("max_ready_seconds", 3600):
            raise ValueError("Prepared candidate/backup expired; prepare a fresh release")
        if self.baseline(plan) != journal["before"]:
            raise ValueError("Production identity changed after preparation")
        container = inspect("container", self.ctl.container_name(self.role, journal["slot"]))
        if container["Id"] != journal["candidate"] or not container["State"]["Running"]:
            raise ValueError("Prepared candidate was replaced or stopped")
        image = inspect("image", plan["images"][self.role])
        assert_container(container, image)
        if self.role == "backend":
            assert_runtime(container, image)
            reported_release(f"http://127.0.0.1:{self.ctl.slot_port(self.role, journal['slot'])}/ready", plan["release"])
        self.ctl.wait_for_health(self.role, journal["slot"])
        return journal

    def activate(self, plan):
        journal = self.ready(plan)
        journal["phase"] = "activating"
        atomic(self.record(plan), journal)  # durable even if HAProxy reload or worker fails
        self.ctl.activate(self.role, journal["slot"], plan["release"])
        self.point_current(plan["release"])
        journal["phase"] = "live"
        journal["activated_at"] = time.time()
        atomic(self.record(plan), journal)
        return self.postflight(plan)

    def postflight(self, plan):
        journal = json.loads(self.record(plan).read_text())
        if journal["identity"] != identity(plan):
            raise ValueError("Postflight identity mismatch")
        actual = self.snapshot()
        if actual["release"] != plan["release"] or actual["source_manifest_sha256"] != plan["source_manifest_sha256"]:
            raise ValueError("Served source identity differs from candidate")
        if actual["container"] != journal["candidate"]:
            raise ValueError("Live container changed")
        if self.role == "backend":
            reported_release("http://127.0.0.1:8000/health", plan["release"])
        self.gate("postflight", plan, actual)
        return actual

    def close(self, plan):
        self.reservation(plan)
        actual = self.postflight(plan)
        self.gate("closing", plan, actual)
        journal = json.loads(self.record(plan).read_text())
        journal["phase"] = "checked"
        atomic(self.record(plan), journal)
        return actual

    def complete(self, plan):
        journal = json.loads(self.record(plan).read_text())
        if journal["identity"] != identity(plan):
            raise ValueError("Completion identity mismatch")
        if journal["phase"] == "complete":
            self.release_reservation(plan)
            return {"complete": True}  # Do not touch a newer candidate's reservation.
        self.reservation(plan)
        if journal["phase"] != "checked":
            raise ValueError("Closing checks have not passed")
        journal["phase"] = "complete"
        atomic(self.record(plan), journal)
        self.release_reservation(plan)
        return {"complete": True}

    def recover(self, plan):
        """Explicit crash/failure recovery; never infer success from a worker restart."""
        if not self.record(plan).exists():
            self.reservation(plan, required=False)
            return self.baseline(plan)  # Refused before this host changed anything.
        journal = json.loads(self.record(plan).read_text())
        if journal["identity"] != identity(plan):
            raise ValueError("Recovery identity mismatch")
        if journal["phase"] == "preparing" and not (STATE / "reservation.json").exists():
            # A crash can occur between the two initial atomic journal/reservation writes.
            # With no reservation we may only acknowledge unchanged production, never reroute it.
            if self.snapshot() != journal["before"]:
                raise ValueError("Unreserved interrupted preparation has production drift")
            journal["phase"] = "recovered"
            atomic(self.record(plan), journal)
            return journal["before"]
        if journal["phase"] == "recovered":
            self.release_reservation(plan)
            return journal["before"]  # Idempotent; never remove another reservation.
        if journal["phase"] == "complete":
            raise ValueError("Completed release needs a new reviewed rollback operation")
        self.reservation(plan)
        state = self.ctl.read_state()
        current = state.get("active_release")
        if current not in {plan["release"], journal["before"]["release"]}:
            raise ValueError("Another deployment changed production; refuse recovery")
        # Restore routing even if a controller failure happened before its state write.
        before = journal["before"]
        old = inspect("container", self.ctl.container_name(self.role, before["slot"]))
        if old["Id"] != before["container"]:
            raise ValueError("Rollback container changed")
        try:
            unchanged = self.snapshot() == before
        except ValueError:
            unchanged = False
        if not unchanged:
            self.ctl.activate(self.role, before["slot"], before["release"])
            self.point_current(before["release"])
        if self.snapshot() != before:
            raise ValueError("Recovery readback mismatch")
        journal["phase"] = "recovered"
        atomic(self.record(plan), journal)
        self.release_reservation(plan)
        return before


def main():
    if os.geteuid() != 0:
        raise ValueError("Host helper must run through its restricted sudo rule")
    trusted(CONFIG)
    request = json.loads(sys.stdin.buffer.read(65537))
    action = request.get("action")
    if action not in {"snapshot", "prepare", "ready", "activate", "postflight", "close", "complete", "recover"}:
        raise ValueError("Unsupported host operation")
    host = Host(json.loads(CONFIG.read_text()))
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Import on Linux only so the contract/test modules remain usable on Windows.
    import fcntl
    with (STATE / "operation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with contextlib.redirect_stdout(io.StringIO()):
            result = host.snapshot() if action == "snapshot" else getattr(host, action)(validate(request["plan"]))
        # Journals retain backup/gate evidence locally; remote callers receive identities only.
        print(json.dumps({"ok": True, "result": result}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1)

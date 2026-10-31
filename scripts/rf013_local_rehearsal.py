"""Rehearse manual two-role rollback with disposable local Docker resources."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
from threading import Event, Thread
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SLOTCTL_PATH = ROOT / "deploy/slotctl.py"
HAPROXY_IMAGE = "haproxy:3.1-alpine"
POSTGRES_IMAGE = "postgres:16-alpine"
RELEASES = {"blue": "old", "green": "candidate"}
PROBE_SECONDS = 150
PROBE_INTERVAL = 0.5
PROBE_TIMEOUT = 2
ACTION_TIMEOUT = 8
MAX_PG_CONNECTIONS = 60
MAX_RECOVERY_SECONDS = 30


def now() -> str:
    return datetime.now(UTC).isoformat()


def command(*args: str, capture: bool = True, check: bool = True) -> str:
    result = subprocess.run(args, text=True, capture_output=capture, check=check)
    return result.stdout.strip() if capture else ""


def docker(*args: str, capture: bool = True, check: bool = True) -> str:
    return command("docker", *args, capture=capture, check=check)


def source_identity(path: Path) -> tuple[Path, str]:
    path = path.resolve()
    if command("git", "-C", str(path), "rev-parse", "--show-toplevel") != str(path):
        raise ValueError("each source must be a Git worktree root")
    if command("git", "-C", str(path), "rev-parse", "--git-common-dir") != command(
        "git", "-C", str(ROOT), "rev-parse", "--git-common-dir"
    ):
        raise ValueError("sources must be worktrees of this repository")
    if command("git", "-C", str(path), "status", "--porcelain", "--untracked-files=all", "--", "backend", "frontend"):
        raise ValueError("backend and frontend source must have no tracked edits")
    return path, command("git", "-C", str(path), "rev-parse", "HEAD")


def require_local_docker() -> None:
    override = os.environ.get("DOCKER_HOST", "")
    endpoint = json.loads(docker("context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"))
    if (override and not override.startswith("unix://")) or not endpoint.startswith("unix://"):
        raise RuntimeError("RF-013 requires a local Unix-socket Docker engine")


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def request(
    url: str,
    method: str = "GET",
    data: bytes | None = None,
    opener=None,
    content_type: str | None = None,
    timeout: float = PROBE_TIMEOUT,
) -> dict[str, object]:
    started = time.monotonic()
    req = urllib.request.Request(url, data=data, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with (opener.open if opener else urllib.request.urlopen)(req, timeout=timeout) as response:
            body = response.read()
            return {
                "at": now(),
                "status": response.status,
                "release": response.headers.get("X-RF013-Release"),
                "slot": response.headers.get("X-RF013-Slot"),
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "body": body.decode("utf-8", "replace") if url.endswith("/health") or url.endswith("/ready") else None,
            }
    except urllib.error.HTTPError as exc:
        return {
            "at": now(),
            "status": exc.code,
            "release": exc.headers.get("X-RF013-Release"),
            "slot": exc.headers.get("X-RF013-Slot"),
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
        }
    except (OSError, TimeoutError) as exc:
        return {"at": now(), "status": type(exc).__name__, "latency_ms": round((time.monotonic() - started) * 1000, 2)}


class ProbeMonitor:
    def __init__(self, urls: dict[str, str]):
        self.urls = urls
        self.rows: list[dict[str, object]] = []
        self.phase = "initial"
        self.stop = Event()
        self.started = time.monotonic()
        self.thread = Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        with ThreadPoolExecutor(max_workers=3) as pool:
            while not self.stop.is_set() and time.monotonic() - self.started < PROBE_SECONDS:
                phase = self.phase
                futures = {name: pool.submit(request, url) for name, url in self.urls.items()}
                self.rows.append(
                    {
                        "phase": phase,
                        "at": now(),
                        "responses": {name: future.result() for name, future in futures.items()},
                    }
                )
                self.stop.wait(PROBE_INTERVAL)

    def start(self) -> None:
        self.thread.start()

    def finish(self) -> None:
        self.stop.set()
        self.thread.join(timeout=PROBE_TIMEOUT + 2)
        if self.thread.is_alive() or time.monotonic() - self.started > PROBE_SECONDS:
            raise TimeoutError("bounded switch observation exceeded 150 seconds")


class Rehearsal:
    def __init__(self, old: Path, candidate: Path):
        require_local_docker()
        self.old, old_sha = source_identity(old)
        self.candidate, candidate_sha = source_identity(candidate)
        if subprocess.run(
            ["git", "-C", str(candidate), "merge-base", "--is-ancestor", old_sha, candidate_sha]
        ).returncode:
            raise ValueError("old source must be an ancestor of candidate source")
        runs = ROOT / ".codex-work/rf013-runs"
        runs.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="milana-rf013-", dir=runs))
        self.dir.chmod(0o700)
        self.prefix = self.dir.name
        self.network = f"{self.prefix}-net"
        self.storage = f"{self.prefix}-storage"
        self.database = f"{self.prefix}-pgdata"
        self.db_name = f"{self.prefix}-db"
        self.proxy_name = f"{self.prefix}-haproxy"
        self.roles = {
            role: {
                "stable": free_port(),
                "blue": free_port(),
                "green": free_port(),
                "health": "/ready" if role == "backend" else "/login",
            }
            for role in ("backend", "frontend")
        }
        self.urls = {
            "health": f"http://127.0.0.1:{self.roles['backend']['stable']}/health",
            "ready": f"http://127.0.0.1:{self.roles['backend']['stable']}/ready",
            "login": f"http://127.0.0.1:{self.roles['frontend']['stable']}/login",
        }
        self.api_url = f"http://127.0.0.1:{self.roles['backend']['stable']}"
        self.refs = {"old": old_sha, "candidate": candidate_sha}
        self.passwords = {
            "db": secrets.token_hex(24),
            "jwt": secrets.token_hex(32),
            "files": secrets.token_hex(32),
            "admin": "RF013!" + secrets.token_hex(16),
        }
        self.evidence: dict[str, object] = {
            "task": "RF-013 single-host rollback rehearsal",
            "started_at": now(),
            "old": old_sha,
            "candidate": candidate_sha,
            "state_dir": str(self.dir),
            "limits": {
                "probe_seconds": PROBE_SECONDS,
                "probe_interval_seconds": PROBE_INTERVAL,
                "probe_concurrency": 3,
                "request_timeout_seconds": PROBE_TIMEOUT,
                "business_action_timeout_seconds": ACTION_TIMEOUT,
                "postgres_connections": MAX_PG_CONNECTIONS,
                "recovery_seconds": MAX_RECOVERY_SECONDS,
                "memory": {"backend": "1g each", "frontend": "1g each", "postgres": "512m", "haproxy": "128m"},
            },
            "expected": "candidate write readable and updateable by old; injected frontend failure leaves route/state mismatch, then old pair recovers",
            "stop_conditions": "data mismatch, >60 PostgreSQL connections, steady-state 5xx, recovery >30s, probe duration >150s",
            "snapshots": [],
            "events": [],
            "status": "running",
        }
        self.current_role = "backend"
        self.config_slots = {"backend": "blue", "frontend": "blue"}
        self.inject_frontend_failure = False
        self.failure_started: float | None = None
        self.monitor: ProbeMonitor | None = None
        self.slotctl = self._load_slotctl()

    def name(self, role: str, slot: str) -> str:
        return f"{self.prefix}-{role}-{slot}"

    def image(self, role: str, release: str) -> str:
        return f"{self.prefix}-{role}-{release}:local"

    def _load_slotctl(self):
        spec = importlib.util.spec_from_file_location("rf013_slotctl", SLOTCTL_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original_write = module.atomic_write

        def local_write(path: Path, content: str, mode: int = 0o640) -> None:
            if not path.resolve().is_relative_to(self.dir):
                raise RuntimeError("slotctl attempted a non-local write")
            original_write(path, content, mode)

        module.BASE = self.dir
        module.RUNTIME = self.dir
        module.PROXY_PATH = self.dir / "haproxy.cfg"
        module.ROLES = self.roles
        module.container_name = self.name
        module.atomic_write = local_write
        module.proxy_config = self.proxy_config
        module.validate_proxy = self.validate_proxy
        module.run = self.slotctl_run
        return module

    @contextmanager
    def role(self, role: str):
        previous = self.current_role
        self.current_role = role
        self.slotctl.STATE_PATH = self.dir / role / "slots.json"
        try:
            yield
        finally:
            self.current_role = previous

    def state(self, role: str) -> dict[str, object]:
        path = self.dir / role / "slots.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def proxy_config(self, role: str, slot: str) -> str:
        active = {name: str(self.state(name).get("active_slot") or "blue") for name in ("backend", "frontend")}
        active[role] = slot
        self.config_slots = active
        backend_name = self.name("backend", active["backend"])
        frontend_name = self.name("frontend", active["frontend"])
        return f"""global
    master-worker
    log stdout format raw local0

defaults
    log global
    mode http
    option httplog
    timeout connect 3s
    timeout client 10s
    timeout server 10s

frontend rf013_backend
    bind :8000
    default_backend rf013_backend_active

backend rf013_backend_active
    option httpchk GET /ready
    http-check expect status 200
    http-response set-header X-RF013-Release {RELEASES[active["backend"]]}
    http-response set-header X-RF013-Slot {active["backend"]}
    server active {backend_name}:10000 check inter 2s fall 3 rise 2

frontend rf013_frontend
    bind :3000
    default_backend rf013_frontend_active

backend rf013_frontend_active
    option httpchk GET /login
    http-check expect status 200
    http-response set-header X-RF013-Release {RELEASES[active["frontend"]]}
    http-response set-header X-RF013-Slot {active["frontend"]}
    server active {frontend_name}:3000 check inter 2s fall 3 rise 2
"""

    def validate_proxy(self, content: str) -> None:
        with tempfile.NamedTemporaryFile(mode="w", prefix="haproxy-validation-", suffix=".cfg", dir=self.dir) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    self.network,
                    "-v",
                    f"{self.dir}:/cfg:ro",
                    HAPROXY_IMAGE,
                    "haproxy",
                    "-c",
                    "-f",
                    f"/cfg/{Path(stream.name).name}",
                ],
                text=True,
                capture_output=True,
            )
            if result.returncode:
                raise RuntimeError(f"HAProxy rejected local config: {result.stderr.strip()}")

    def slotctl_run(self, *args: str, capture: bool = False) -> str:
        if args[:2] == ("systemctl", "reload"):
            docker("cp", str(self.dir / "haproxy.cfg"), f"{self.proxy_name}:/tmp/haproxy-next.cfg")
            docker("exec", "--user", "0", self.proxy_name, "chmod", "644", "/tmp/haproxy-next.cfg")
            check = subprocess.run(
                ["docker", "exec", self.proxy_name, "haproxy", "-c", "-f", "/tmp/haproxy-next.cfg"],
                text=True,
                capture_output=True,
            )
            if check.returncode:
                raise RuntimeError(f"HAProxy rejected copied config: {check.stderr.strip()}")
            docker("exec", "--user", "0", self.proxy_name, "mv", "/tmp/haproxy-next.cfg", "/tmp/haproxy.cfg")
            docker("kill", "--signal=USR2", self.proxy_name)
            endpoint = "ready" if self.current_role == "backend" else "login"
            expected = RELEASES[self.config_slots[self.current_role]]
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                response = request(self.urls[endpoint])
                if response["status"] == 200 and response["release"] == expected:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError(f"HAProxy did not route {self.current_role} to {expected} after reload")
            if self.inject_frontend_failure and self.current_role == "frontend":
                self.inject_frontend_failure = False
                docker("stop", "--time", "0", self.name("frontend", "green"))
                self.failure_started = time.monotonic()
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and request(self.urls["login"])["status"] == 200:
                    time.sleep(0.2)
                self.event("injected_failure", "stopped candidate frontend immediately after HAProxy reload")
            return ""
        if args[:3] == ("docker", "image", "inspect"):
            docker("image", "inspect", args[3])
            return ""
        if args[:2] == ("docker", "run"):
            parts = list(args)
            name = parts[parts.index("--name") + 1]
            if not name.startswith(self.prefix + "-"):
                raise RuntimeError("refusing an unscoped container")
            role = "backend" if "-backend-" in name else "frontend"
            parts[parts.index("--restart") + 1] = "no"
            if role == "backend":
                mount = parts.index("/app/storage:/app/storage")
                parts[mount] = f"{self.storage}:/app/storage"
            else:
                parts[-1:-1] = ["-e", f"API_URL=http://{self.proxy_name}:8000"]
            parts[-1:-1] = ["--network", self.network, "--memory", "1g", "--label", f"rf013.project={self.prefix}"]
            return command(*parts, capture=capture)
        if args[:2] == ("docker", "logs"):
            return command(*args, capture=capture)
        raise RuntimeError(f"unsupported slotctl command: {args[:2]}")

    def event(self, kind: str, detail: str) -> None:
        self.evidence["events"].append({"at": now(), "kind": kind, "detail": detail})

    def build(self, role: str, release: str, source: Path) -> None:
        image = self.image(role, release)
        build = ["docker", "build", "-t", image]
        if role == "frontend":
            # Rewrites are baked at build time; keep them on this run's local network.
            build += [
                "-f", str(source / "frontend/Dockerfile"),
                "--build-arg", f"API_URL=http://{self.proxy_name}:8000",
                "--build-arg", "NEXT_PUBLIC_API_URL=", str(source),
            ]
        else:
            build += [str(source / "backend")]
        log = self.dir / f"build-{role}-{release}.log"
        with log.open("w") as stream:
            result = subprocess.run(build, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"{image} build failed; see {log}")
        inspected = json.loads(docker("image", "inspect", image))[0]
        config = inspected["Config"]
        if role == "frontend" and (
            "NODE_ENV=production" not in config.get("Env", [])
            or config.get("Cmd") != ["node", "server.js"]
        ):
            raise RuntimeError(f"{image} is not the standalone production frontend")
        self.evidence.setdefault("images", []).append({
            "role": role, "release": release, "image": image, "id": inspected["Id"],
            "dockerfile": str(source / ("frontend/Dockerfile" if role == "frontend" else "backend/Dockerfile")),
            "command": config.get("Cmd"), "entrypoint": config.get("Entrypoint"),
            "user": config.get("User"),
            "node_env": next((item for item in config.get("Env", []) if item.startswith("NODE_ENV=")), None),
        })
        self.event("image_built", image)

    def prepare(self) -> None:
        docker("pull", HAPROXY_IMAGE, capture=False)
        docker("network", "create", self.network)
        docker("volume", "create", self.storage)
        docker("volume", "create", self.database)
        env = self.dir / "shared/backend.env"
        env.parent.mkdir(parents=True)
        env.write_text(
            "\n".join(
                [
                    "ENV=development",
                    f"DATABASE_URL=postgresql+psycopg2://rf013:{self.passwords['db']}@{self.db_name}:5432/rf013",
                    f"JWT_SECRET={self.passwords['jwt']}",
                    f"FILE_SIGNING_SECRET={self.passwords['files']}",
                    "SHARED_STORE_URL=sqlite:////app/storage/shared-store.db",
                    "INITIAL_ADMIN_EMAIL=rf013-admin@example.com",
                    f"INITIAL_ADMIN_PASSWORD={self.passwords['admin']}",
                    "RUN_SEED_ON_STARTUP=true",
                    "SEED_DEMO_USERS=false",
                    "SEED_SAMPLE_DATA=false",
                    "IMPORT_LEGACY_MODELS=false",
                    "GLOBAL_RATE_LIMIT_ENABLED=false",
                    f"CORS_ORIGINS=http://127.0.0.1:{self.roles['frontend']['stable']}",
                ]
            )
            + "\n"
        )
        env.chmod(0o600)
        docker(
            "run",
            "-d",
            "--name",
            self.db_name,
            "--network",
            self.network,
            "--label",
            f"rf013.project={self.prefix}",
            "--memory",
            "512m",
            "-e",
            "POSTGRES_USER=rf013",
            "-e",
            "POSTGRES_DB=rf013",
            "-e",
            f"POSTGRES_PASSWORD={self.passwords['db']}",
            "-v",
            f"{self.database}:/var/lib/postgresql/data",
            POSTGRES_IMAGE,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if (
                subprocess.run(
                    ["docker", "exec", self.db_name, "pg_isready", "-U", "rf013", "-d", "rf013"], capture_output=True
                ).returncode
                == 0
            ):
                break
            time.sleep(1)
        else:
            raise TimeoutError("local PostgreSQL did not become ready")
        self.event("postgres_ready", self.db_name)
        for release, source in (("old", self.old), ("candidate", self.candidate)):
            for role in ("backend", "frontend"):
                self.build(role, release, source)

    def stage(self, role: str, slot: str) -> None:
        with self.role(role):
            self.slotctl.stage(role, slot, RELEASES[slot], self.image(role, RELEASES[slot]))
        self.event("staged", f"{role} {slot} {RELEASES[slot]}")

    def activate(self, role: str, slot: str) -> None:
        with self.role(role):
            self.slotctl.activate(role, slot, RELEASES[slot])
        self.event("activated", f"{role} {slot} {RELEASES[slot]}")

    def set_current(self, release: str) -> None:
        for role in ("backend", "frontend"):
            link = self.dir / f"current-{role}"
            temp = self.dir / f"current-{role}.next"
            temp.symlink_to(self.old if release == "old" else self.candidate)
            temp.replace(link)

    def start_proxy(self) -> None:
        content = self.proxy_config("frontend", "blue")
        self.validate_proxy(content)
        self.slotctl.atomic_write(self.dir / "haproxy.cfg", content)
        docker(
            "run",
            "-d",
            "--name",
            self.proxy_name,
            "--network",
            self.network,
            "--label",
            f"rf013.project={self.prefix}",
            "--memory",
            "128m",
            "-p",
            f"127.0.0.1:{self.roles['backend']['stable']}:8000",
            "-p",
            f"127.0.0.1:{self.roles['frontend']['stable']}:3000",
            "-v",
            f"{self.dir}:/cfg:ro",
            HAPROXY_IMAGE,
            "sh",
            "-c",
            "cp /cfg/haproxy.cfg /tmp/haproxy.cfg && exec haproxy -W -db -f /tmp/haproxy.cfg",
        )
        with self.role("backend"):
            self.slotctl.wait_for_stable("backend")
        with self.role("frontend"):
            self.slotctl.wait_for_stable("frontend")
        for role in ("backend", "frontend"):
            with self.role(role):
                self.slotctl.write_state(
                    {
                        "role": role,
                        "active_slot": "blue",
                        "active_release": "old",
                        "rollback_slot": None,
                        "rollback_release": None,
                    }
                )
        self.set_current("old")

    def sql(self, statement: str) -> str:
        return docker("exec", self.db_name, "psql", "-U", "rf013", "-d", "rf013", "-Atc", statement)

    def snapshot(self, label: str) -> None:
        config = self.dir / "haproxy.cfg"
        config_copy = self.dir / f"haproxy-{label}.cfg"
        if config.exists():
            shutil.copyfile(config, config_copy)
        states = {role: self.state(role) for role in ("backend", "frontend")}
        links = {
            role: os.readlink(self.dir / f"current-{role}") if (self.dir / f"current-{role}").is_symlink() else None
            for role in ("backend", "frontend")
        }
        routes = {name: request(url) for name, url in self.urls.items()}
        connections = int(
            self.sql("SELECT count(*) FROM pg_stat_activity WHERE datname='rf013' AND backend_type='client backend'")
        )
        if connections > MAX_PG_CONNECTIONS:
            raise RuntimeError("PostgreSQL connection cap exceeded")
        revision = self.sql("SELECT version_num FROM alembic_version")
        row = self.sql(
            "SELECT coalesce(value_json->>'default_currency', '<missing>') FROM system_settings WHERE key='financial'"
        )
        names = [
            self.proxy_name,
            self.db_name,
            *(self.name(role, slot) for role in ("backend", "frontend") for slot in ("blue", "green")),
        ]
        containers = {}
        for name in names:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", name], text=True, capture_output=True
            )
            containers[name] = result.stdout.strip() if result.returncode == 0 else "absent"
            if result.returncode == 0:
                log_path = self.dir / f"{label}-{name}.log"
                log = subprocess.run(
                    ["docker", "logs", "--timestamps", "--tail", "60", name], text=True, capture_output=True, check=True
                )
                log_path.write_text(log.stdout + log.stderr)
        self.evidence["snapshots"].append(
            {
                "label": label,
                "at": now(),
                "states": states,
                "symlinks": links,
                "routes": routes,
                "haproxy_config": str(config_copy) if config.exists() else None,
                "haproxy_sha256": hashlib.sha256(config.read_bytes()).hexdigest() if config.exists() else None,
                "database_revision": revision,
                "financial_currency": row or None,
                "postgres_connections": connections,
                "containers": containers,
            }
        )
        self.save()

    def save(self) -> None:
        (self.dir / "evidence.json").write_text(json.dumps(self.evidence, indent=2) + "\n")

    def authenticated_opener(self):
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        data = urllib.parse.urlencode(
            {"username": "rf013-admin@example.com", "password": self.passwords["admin"]}
        ).encode()
        url = self.api_url + "/api/auth/login"
        response = request(url, "POST", data, opener, "application/x-www-form-urlencoded", ACTION_TIMEOUT)
        if response["status"] != 200:
            raise RuntimeError(f"local admin login failed: {response['status']}")
        return opener

    def setting(self, opener) -> dict[str, object]:
        url = self.api_url + "/api/settings"
        req = urllib.request.Request(url)
        with opener.open(req, timeout=ACTION_TIMEOUT) as response:
            if response.status != 200:
                raise RuntimeError(f"settings read returned {response.status}")
            return json.load(response)

    def write_currency(self, opener, currency: str) -> None:
        url = self.api_url + "/api/settings/financial"
        req = urllib.request.Request(
            url,
            data=json.dumps({"default_currency": currency}).encode(),
            method="PATCH",
            headers={"Content-Type": "application/json"},
        )
        with opener.open(req, timeout=ACTION_TIMEOUT) as response:
            if response.status != 200 or json.load(response)["default_currency"] != currency:
                raise RuntimeError("settings write was not acknowledged")

    def assert_routes(self, backend: str, frontend: str) -> None:
        expected = {"health": backend, "ready": backend, "login": frontend}
        deadline = time.monotonic() + 20
        consecutive = 0
        while time.monotonic() < deadline:
            results = {name: request(url) for name, url in self.urls.items()}
            if all(
                results[name]["status"] == 200 and results[name]["release"] == release
                for name, release in expected.items()
            ):
                consecutive += 1
                if consecutive == 3:
                    return
            else:
                consecutive = 0
            time.sleep(1)
        raise RuntimeError(f"stable routes did not settle on {expected}: {results}")

    def run(self) -> None:
        self.prepare()
        self.stage("backend", "blue")
        self.stage("frontend", "blue")
        self.start_proxy()
        self.assert_routes("old", "old")
        self.snapshot("old_active")
        opener = self.authenticated_opener()
        if self.setting(opener)["financial"]["default_currency"] != "USD":
            raise RuntimeError("old fixture did not start with USD")
        self.stage("backend", "green")
        self.stage("frontend", "green")
        self.snapshot("candidate_staged")
        self.monitor = ProbeMonitor(self.urls)
        self.monitor.start()

        self.monitor.phase = "backend_forward"
        self.activate("backend", "green")
        self.snapshot("backend_forward")
        self.monitor.phase = "frontend_forward"
        self.activate("frontend", "green")
        self.set_current("candidate")
        self.assert_routes("candidate", "candidate")
        self.snapshot("candidate_active")
        opener = self.authenticated_opener()
        self.write_currency(opener, "UZS")
        if self.setting(opener)["financial"]["default_currency"] != "UZS":
            raise RuntimeError("candidate could not read its write")
        self.snapshot("candidate_write")

        self.monitor.phase = "backend_rollback"
        self.activate("backend", "blue")
        self.snapshot("backend_rollback")
        self.monitor.phase = "frontend_rollback"
        self.activate("frontend", "blue")
        self.set_current("old")
        self.assert_routes("old", "old")
        opener = self.authenticated_opener()
        if self.setting(opener)["financial"]["default_currency"] != "UZS":
            raise RuntimeError("old version could not read candidate-written data")
        self.write_currency(opener, "USD")
        if self.setting(opener)["financial"]["default_currency"] != "USD":
            raise RuntimeError("old version could not continue writing")
        self.snapshot("old_restored")

        self.monitor.phase = "backend_partial_forward"
        self.activate("backend", "green")
        self.snapshot("backend_partial_forward")
        self.monitor.phase = "frontend_post_reload_failure"
        self.inject_frontend_failure = True
        try:
            self.activate("frontend", "green")
        except RuntimeError as exc:
            self.event("expected_activation_failure", str(exc))
        else:
            raise RuntimeError("injected frontend post-reload failure did not fail activation")
        self.snapshot("failed_frontend_switch")
        if self.state("frontend").get("active_slot") != "blue":
            raise RuntimeError("expected frontend state to remain blue after failed activation")
        if f"server active {self.name('frontend', 'green')}:3000" not in (self.dir / "haproxy.cfg").read_text():
            raise RuntimeError("expected frontend HAProxy route/state mismatch was not present")

        recovery_started = time.monotonic()
        self.monitor.phase = "manual_reconciliation"
        self.activate("backend", "blue")
        self.activate("frontend", "blue")
        for role in ("backend", "frontend"):
            with self.role(role):
                self.slotctl.write_state(
                    {
                        "role": role,
                        "active_slot": "blue",
                        "active_release": "old",
                        "rollback_slot": None,
                        "rollback_release": None,
                    }
                )
        self.set_current("old")
        self.assert_routes("old", "old")
        opener = self.authenticated_opener()
        if self.setting(opener)["financial"]["default_currency"] != "USD":
            raise RuntimeError("reconciled old pair could not read persisted data")
        recovered_in = round(time.monotonic() - recovery_started, 2)
        self.evidence["recovery_seconds"] = recovered_in
        if self.failure_started is not None:
            self.evidence["failure_to_recovery_seconds"] = round(time.monotonic() - self.failure_started, 2)
        if recovered_in > MAX_RECOVERY_SECONDS:
            raise TimeoutError("manual reconciliation exceeded 30 seconds")
        self.snapshot("reconciled_old")
        self.monitor.finish()
        self.evidence["probes"] = self.monitor.rows
        self.evidence["status"] = "pass"

    def cleanup(self) -> None:
        if self.monitor:
            self.monitor.stop.set()
            self.monitor.thread.join(timeout=PROBE_TIMEOUT + 2) if self.monitor.thread.is_alive() else None
            self.evidence["probes"] = self.monitor.rows
        containers = [
            self.proxy_name,
            *(self.name(role, slot) for role in ("backend", "frontend") for slot in ("blue", "green")),
            self.db_name,
        ]
        for name in containers:
            log = subprocess.run(
                ["docker", "logs", "--timestamps", "--tail", "200", name], text=True, capture_output=True
            )
            if log.returncode == 0:
                (self.dir / f"final-{name}.log").write_text(log.stdout + log.stderr)
            docker("rm", "-f", name, check=False)
        for volume in (self.storage, self.database):
            docker("volume", "rm", volume, check=False)
        docker("network", "rm", self.network, check=False)
        for release in ("old", "candidate"):
            for role in ("backend", "frontend"):
                docker("image", "rm", self.image(role, release), check=False)
        (self.dir / "shared/backend.env").unlink(missing_ok=True)
        self.evidence["cleanup_at"] = now()
        self.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-source", type=Path, required=True)
    parser.add_argument("--candidate-source", type=Path, default=ROOT)
    args = parser.parse_args()
    rehearsal = Rehearsal(args.old_source, args.candidate_source)
    try:
        rehearsal.run()
    except Exception as exc:
        rehearsal.evidence["status"] = "fail"
        rehearsal.event("failure", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        rehearsal.evidence["finished_at"] = now()
        rehearsal.cleanup()
        print(f"RF-013 {rehearsal.evidence['status']}; evidence: {rehearsal.dir / 'evidence.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

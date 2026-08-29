#!/usr/bin/env python3
"""Guarded blue-green runtime manager for one Milana ERP application VM.

The tool is intentionally host-local and must run as root. It never builds an
image, edits application source, or accesses business rows. It stages an
already-built image on the inactive loopback slot, warms it, and atomically
reloads a dedicated HAProxy listener after health checks pass.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


BASE = Path("/opt/milana-erp")
RUNTIME = BASE / "runtime"
STATE_PATH = RUNTIME / "slots.json"
PROXY_PATH = RUNTIME / "haproxy.cfg"
SERVICE_PATH = Path("/etc/systemd/system/milana-router.service")
ROLES = {
    "backend": {"stable": 8000, "blue": 18001, "green": 18002, "health": "/health"},
    "frontend": {"stable": 3000, "blue": 13001, "green": 13002, "health": "/login"},
}


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("slotctl must run as root")


def atomic_write(path: Path, content: str, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def write_state(state: dict[str, object]) -> None:
    state["updated_at"] = datetime.now(UTC).isoformat()
    atomic_write(STATE_PATH, json.dumps(state, indent=2, sort_keys=True) + "\n")


def container_name(role: str, slot: str) -> str:
    return f"milana-{role}-{slot}"


def slot_port(role: str, slot: str) -> int:
    return int(ROLES[role][slot])


def wait_for_health(role: str, slot: str, attempts: int = 60) -> None:
    path = str(ROLES[role]["health"])
    url = f"http://127.0.0.1:{slot_port(role, slot)}{path}"
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - retain last network failure
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Candidate health did not become ready: {url}: {last_error}")


def warm(role: str, slot: str) -> None:
    port = slot_port(role, slot)
    paths = ["/health"] if role == "backend" else ["/login", "/presentation"]
    for _ in range(3):
        for path in paths:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=15) as response:
                if response.status != 200:
                    raise RuntimeError(f"Warm-up failed: {role} {path} HTTP {response.status}")


def inspect_image(image: str) -> None:
    run("docker", "image", "inspect", image)


def remove_inactive_container(role: str, slot: str) -> None:
    state = read_state()
    if state.get("role") == role and state.get("active_slot") == slot:
        raise RuntimeError(f"Refusing to replace active {role} slot {slot}")
    name = container_name(role, slot)
    exists = subprocess.run(
        ["docker", "container", "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if exists:
        run("docker", "rm", "-f", name)


def stage(role: str, slot: str, release: str, image: str) -> None:
    inspect_image(image)
    remove_inactive_container(role, slot)
    name = container_name(role, slot)
    port = str(slot_port(role, slot))
    command = [
        "docker", "run", "-d", "--name", name, "--restart", "unless-stopped",
        "--label", f"milana.release={release}", "--label", f"milana.slot={slot}",
        "--label", f"milana.role={role}", "-p", f"127.0.0.1:{port}:{10000 if role == 'backend' else 3000}",
    ]
    if role == "backend":
        command.extend([
            "--env-file", str(BASE / "shared/backend.env"),
            "-e", "DB_POOL_SIZE=8", "-e", "DB_MAX_OVERFLOW=4", "-e", "WEB_CONCURRENCY=2",
            "-v", "/app/storage:/app/storage",
        ])
    command.append(image)
    run(*command)
    try:
        wait_for_health(role, slot)
        warm(role, slot)
    except Exception:
        run("docker", "logs", "--tail", "200", name)
        raise
    print(json.dumps({"staged": True, "role": role, "slot": slot, "release": release, "image": image}))


def proxy_config(role: str, slot: str) -> str:
    stable = int(ROLES[role]["stable"])
    port = slot_port(role, slot)
    health = str(ROLES[role]["health"])
    return f"""global
    master-worker
    log stdout format raw local0

defaults
    log global
    mode http
    option httplog
    option http-keep-alive
    option forwardfor
    timeout connect 3s
    timeout client 60s
    timeout server 60s
    timeout http-request 30s

frontend milana_public
    bind 0.0.0.0:{stable}
    default_backend milana_active

backend milana_active
    option httpchk GET {health}
    http-check expect status 200
    server active 127.0.0.1:{port} check inter 2s fall 3 rise 2
"""


def validate_proxy(content: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as stream:
        stream.write(content)
        temporary = stream.name
    try:
        run("haproxy", "-c", "-f", temporary)
    finally:
        os.unlink(temporary)


def service_content() -> str:
    return """[Unit]
Description=Milana ERP stable-port router
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/usr/sbin/haproxy -Ws -f /opt/milana-erp/runtime/haproxy.cfg -p /run/milana-router.pid
ExecReload=/bin/kill -USR2 $MAINPID
KillMode=mixed
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
"""


def install_router(role: str, slot: str, release: str, stop_legacy: bool) -> None:
    if shutil.which("haproxy") is None:
        raise RuntimeError("Install the distribution haproxy package before bootstrapping")
    wait_for_health(role, slot)
    content = proxy_config(role, slot)
    validate_proxy(content)
    atomic_write(PROXY_PATH, content)
    atomic_write(SERVICE_PATH, service_content(), mode=0o644)
    run("systemctl", "daemon-reload")
    legacy_stopped = False
    if stop_legacy:
        if role == "backend":
            run("docker", "stop", "milana-backend")
        else:
            run("systemctl", "stop", "milana-frontend")
        legacy_stopped = True
    try:
        run("systemctl", "enable", "--now", "milana-router")
        wait_for_stable(role)
    except Exception:
        subprocess.run(["systemctl", "stop", "milana-router"], check=False)
        if legacy_stopped:
            if role == "backend":
                subprocess.run(["docker", "start", "milana-backend"], check=False)
            else:
                subprocess.run(["systemctl", "start", "milana-frontend"], check=False)
            wait_for_stable(role)
        raise
    write_state({"role": role, "active_slot": slot, "active_release": release, "rollback_slot": None, "rollback_release": None})


def wait_for_stable(role: str) -> None:
    url = f"http://127.0.0.1:{ROLES[role]['stable']}{ROLES[role]['health']}"
    for _ in range(30):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    raise RuntimeError(f"Stable listener did not become healthy: {url}")


def activate(role: str, slot: str, release: str) -> None:
    state = read_state()
    if state.get("role") not in (None, role):
        raise RuntimeError("Runtime state belongs to another role")
    wait_for_health(role, slot)
    content = proxy_config(role, slot)
    validate_proxy(content)
    atomic_write(PROXY_PATH, content)
    run("systemctl", "reload", "milana-router")
    wait_for_stable(role)
    previous_slot = state.get("active_slot")
    previous_release = state.get("active_release")
    write_state({
        "role": role,
        "active_slot": slot,
        "active_release": release,
        "rollback_slot": previous_slot,
        "rollback_release": previous_release,
    })
    print(json.dumps(read_state(), indent=2, sort_keys=True))


def benchmark(slot: str, output: Path) -> None:
    name = container_name("backend", slot)
    result = run(
        "docker", "exec", name, "python", "/app/scripts/benchmark_release_search.py",
        "--base-url", "http://127.0.0.1:10000", capture=True,
    )
    parsed = json.loads(result)
    atomic_write(output, json.dumps(parsed, indent=2, sort_keys=True) + "\n", mode=0o644)
    print(output)


def main() -> None:
    require_root()
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage_parser = subparsers.add_parser("stage")
    stage_parser.add_argument("--role", choices=ROLES, required=True)
    stage_parser.add_argument("--slot", choices=("blue", "green"), required=True)
    stage_parser.add_argument("--release", required=True)
    stage_parser.add_argument("--image", required=True)

    install_parser = subparsers.add_parser("install-router")
    install_parser.add_argument("--role", choices=ROLES, required=True)
    install_parser.add_argument("--slot", choices=("blue", "green"), required=True)
    install_parser.add_argument("--release", required=True)
    install_parser.add_argument("--stop-legacy", action="store_true")

    activate_parser = subparsers.add_parser("activate")
    activate_parser.add_argument("--role", choices=ROLES, required=True)
    activate_parser.add_argument("--slot", choices=("blue", "green"), required=True)
    activate_parser.add_argument("--release", required=True)

    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_parser.add_argument("--slot", choices=("blue", "green"), required=True)
    benchmark_parser.add_argument("--output", type=Path, required=True)

    subparsers.add_parser("status")
    args = parser.parse_args()
    if args.command == "stage":
        stage(args.role, args.slot, args.release, args.image)
    elif args.command == "install-router":
        install_router(args.role, args.slot, args.release, args.stop_legacy)
    elif args.command == "activate":
        activate(args.role, args.slot, args.release)
    elif args.command == "benchmark":
        benchmark(args.slot, args.output)
    else:
        print(json.dumps(read_state(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

"""Run SEC04 checks against disposable, loopback-only Docker data."""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "scripts/sec04_local.compose.yml"
FIXTURE = ROOT / "scripts/sec04_local_fixture.py"
STATE_DIR = ROOT / ".codex-work/sec04-local-stack"
STATE_FILE = STATE_DIR / "state.json"
ENV_FILE = STATE_DIR / "stack.env"
BACKEND_URL = "http://127.0.0.1:18080"


def git(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def candidate_identity(source: Path) -> str:
    source = source.resolve()
    if git(source, "rev-parse", "--show-toplevel") != str(source):
        raise ValueError("candidate must be the root of a Git worktree")
    if git(source, "rev-parse", "--git-common-dir") != git(ROOT, "rev-parse", "--git-common-dir"):
        raise ValueError("candidate must be a worktree of this repository")
    changes = git(source, "status", "--porcelain", "--untracked-files=no").splitlines()
    if changes:
        original = git(source, "show", "HEAD:frontend/next-env.d.ts")
        generated = original.replace('"./.next/types/', '"./.next/dev/types/')
        if changes != ["M frontend/next-env.d.ts"] or (source / "frontend/next-env.d.ts").read_text().strip() != generated:
            raise ValueError("candidate must have no tracked edits beyond Next dev's generated type paths")
    if not (source / "backend/Dockerfile").is_file() or not (source / "frontend/package.json").is_file():
        raise ValueError("candidate is missing the ERP backend or frontend")
    return git(source, "rev-parse", "HEAD")


def read_state() -> dict[str, str]:
    state = json.loads(STATE_FILE.read_text())
    if not re.fullmatch(r"milana-sec04-local-[0-9a-f]{8}", state["project"]):
        raise ValueError("refusing to operate on an unrecognized Compose project")
    return state


def require_local_docker() -> None:
    host_override = os.environ.get("DOCKER_HOST", "")
    endpoint = json.loads(subprocess.check_output(
        ["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"],
        text=True).strip())
    if (host_override and not host_override.startswith("unix://")) or not endpoint.startswith("unix://"):
        raise RuntimeError("SEC04 stack requires a local Unix-socket Docker daemon")


def compose(state: dict[str, str], *args: str, input_text: str | None = None, capture: bool = False):
    require_local_docker()
    command = [
        "docker", "compose", "--env-file", str(ENV_FILE),
        "-p", state["project"], "-f", str(COMPOSE), *args,
    ]
    return subprocess.run(command, input=input_text, text=True, check=True,
                          capture_output=capture)


def up(candidate: Path) -> None:
    if STATE_FILE.exists():
        raise ValueError("a SEC04 stack already exists; use info, reset, or down")
    require_local_docker()
    commit = candidate_identity(candidate)
    candidate = candidate.resolve()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "project": f"milana-sec04-local-{secrets.token_hex(4)}",
        "candidate": str(candidate),
        "commit": commit,
    }
    values = {
        "SEC04_BACKEND_CONTEXT": str(candidate / "backend"),
        "SEC04_DB_PASSWORD": secrets.token_hex(24),
        "SEC04_JWT_SECRET": secrets.token_hex(32),
        "SEC04_FILE_SIGNING_SECRET": secrets.token_hex(32),
        "SEC04_ADMIN_PASSWORD": "Sec04!" + secrets.token_hex(16),
        "SEC04_VIEWER_PASSWORD": "Sec04!" + secrets.token_hex(16),
    }
    descriptor = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    STATE_FILE.chmod(0o600)
    compose(state, "up", "--build", "-d")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with urlopen(BACKEND_URL + "/ready", timeout=3) as response:
                if response.status == 200:
                    print(f"SEC04 backend ready: {BACKEND_URL}; candidate {commit}")
                    print(f"Frontend: cd {shlex.quote(str(candidate / 'frontend'))}")
                    print(f"Then run: API_URL={BACKEND_URL} npm ci --legacy-peer-deps")
                    print(f"Then run: API_URL={BACKEND_URL} npm run dev -- --hostname 127.0.0.1")
                    return
        except OSError:
            pass
        time.sleep(2)
    raise TimeoutError("SEC04 backend did not become ready; inspect this project's Compose logs")


def down() -> None:
    state = read_state()
    compose(state, "down", "--volumes", "--remove-orphans")
    STATE_FILE.unlink()
    ENV_FILE.unlink()
    STATE_DIR.rmdir()


def fixture(action: str) -> None:
    state = read_state()
    compose(state, "exec", "-T", "backend", "python", "-", action,
            input_text=FIXTURE.read_text())


def local_env() -> dict[str, str]:
    read_state()
    values = dict(line.split("=", 1) for line in ENV_FILE.read_text().splitlines())
    return {**os.environ,
            "SEC04_VIEWER_PASSWORD": values["SEC04_VIEWER_PASSWORD"],
            "SEC04_ADMIN_PASSWORD": values["SEC04_ADMIN_PASSWORD"]}


def pg_connections() -> int:
    result = compose(read_state(), "exec", "-T", "db", "psql", "-U", "sec04", "-d", "sec04",
                     "-Atc", "SELECT count(*) FROM pg_stat_activity WHERE datname='sec04' AND backend_type='client backend'",
                     capture=True)
    return int(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "reset", "down", "info", "fixture", "revoke", "readback", "browser", "stress"])
    parser.add_argument("--candidate", type=Path, help="clean local SEC04 Git worktree, for up only")
    args = parser.parse_args()
    if args.action == "up":
        if args.candidate is None:
            parser.error("up requires --candidate")
        up(args.candidate)
    elif args.action == "reset":
        if args.candidate is not None:
            parser.error("reset reuses the existing candidate; --candidate is not accepted")
        source = Path(read_state()["candidate"])
        down()
        up(source)
    elif args.candidate is not None:
        parser.error("--candidate is accepted only by up")
    elif args.action == "down":
        down()
    elif args.action in {"fixture", "revoke", "readback"}:
        fixture(args.action)
    elif args.action == "info":
        state = read_state()
        print(json.dumps({**state, "backend_url": BACKEND_URL,
                          "frontend_url": "http://127.0.0.1:3000"}, indent=2))
    elif args.action == "browser":
        subprocess.run(["node", "scripts/sec04-live.browser.mjs"], cwd=ROOT / "frontend",
                       env=local_env(), check=True)
    elif args.action == "stress":
        subprocess.run([sys.executable, str(ROOT / "scripts/sec04_local_stress.py")],
                       env=local_env(), check=True, timeout=45)


if __name__ == "__main__":
    main()

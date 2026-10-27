"""Run the backend suite and S06 races against disposable local PostgreSQL 16."""

import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres:16-alpine"  # Same database image as the SEC04 local stack.


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def require_local_docker() -> None:
    override = os.environ.get("DOCKER_HOST", "")
    endpoint = json.loads(docker("context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"))
    if (override and not override.startswith("unix://")) or not endpoint.startswith("unix://"):
        raise RuntimeError("PostgreSQL test runner requires a local Unix-socket Docker daemon")


def main() -> int:
    require_local_docker()
    name = f"milana-postgres-tests-{secrets.token_hex(4)}"
    started = False
    try:
        docker(
            "run", "--detach", "--rm", "--name", name,
            "--publish", "127.0.0.1::5432",
            "--env", "POSTGRES_USER=postgres",
            "--env", "POSTGRES_DB=milana_test",
            "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
            IMAGE,
        )
        started = True
        address = docker("port", name, "5432/tcp")
        match = re.fullmatch(r"127\.0\.0\.1:(\d+)", address)
        if not match:
            raise RuntimeError(f"PostgreSQL test port is not loopback: {address}")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "postgres", "-d", "milana_test"],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise TimeoutError("Disposable PostgreSQL did not become ready within 60 seconds")

        base_url = f"postgresql+psycopg2://postgres@127.0.0.1:{match.group(1)}"
        url = f"{base_url}/milana_test"
        env = {
            **os.environ,
            "STABILIZATION_POSTGRES_URL": url,
            "S06_POSTGRES_URL": url,
            "FN04_TEST_PG_ADMIN_URL": f"{base_url}/postgres",
            "DATABASE_URL": url,
        }
        print(f"PostgreSQL 16 ready on loopback port {match.group(1)}; running default backend suite", flush=True)
        suite = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT / "backend", env=env)
        print("Running separately collected S06 stock-adjustment races", flush=True)
        s06 = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "backend/tests/test_stock_adjustment_postgres.py"],
            cwd=ROOT, env=env,
        )
        return 0 if suite.returncode == s06.returncode == 0 else 1
    finally:
        if started:
            subprocess.run(["docker", "stop", name], check=True, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())

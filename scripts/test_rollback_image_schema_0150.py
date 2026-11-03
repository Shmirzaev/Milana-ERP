"""Exercise the immutable rollback image's real CMD against owned schema-0150 PG.

No host ports, production endpoints, mounted source, seeds, or startup bypasses.
Run after publishing: --image ghcr.io/owner/image@sha256:... --revision COMMIT.
"""
import argparse
import json
import re
import secrets
import subprocess
import time
from unittest.mock import patch

HEAD = "0150_package_customer_release"
LABEL = "milana.rollback-schema-0150-owner"
COUNTER_URL = "sqlite:///app/storage/rollback-qa-counters.sqlite"
DEFAULT_CMD = ["sh", "-c", "PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini upgrade head && PYTHONPATH=/app:/app/backend uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers ${WEB_CONCURRENCY:-2}"]
WORKERS = """
import json,os,pathlib
workers=[]
for path in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
 try:
  command=path.read_bytes()
  if int(path.parent.name)!=os.getpid() and b'multiprocessing.spawn' in command and b'spawn_main' in command:
   workers.append(int(path.parent.name))
 except (FileNotFoundError, ProcessLookupError, PermissionError):
  pass
print(json.dumps(sorted(workers)))
"""
PROBES = """
import json,urllib.request
for path,expected in [('/health','ok'),('/ready','ready')]:
 with urllib.request.urlopen('http://127.0.0.1:10000'+path,timeout=3) as response:
  assert response.status==200
  data=json.load(response)
  assert data['status']==expected,data
  if path=='/ready': assert data['checks']['postgresql']=='ok'
"""
STRICT = """
import os
from app.core.config import settings
from app.core.proxy_trust import validate_proxy_runtime_configuration
from app.core.shared_store import SQLiteSharedCounterStore,get_shared_counter_store
assert settings.is_production and settings.strict_security_required
assert not settings.STARTUP_SCHEMA_SYNC
assert os.environ['RUN_SEED_ON_STARTUP']=='false'
assert os.environ['WEB_CONCURRENCY']=='2'
assert settings.GLOBAL_RATE_LIMIT_ENABLED and settings.AUTH_MAX_FAILED_ATTEMPTS>0
assert settings.AUTH_LOCKOUT_SECONDS>0 and settings.shared_store_url
assert settings.shared_store_url=='sqlite:///app/storage/rollback-qa-counters.sqlite'
settings.validate_runtime_security()
validate_proxy_runtime_configuration(strict_security_required=True)
store=get_shared_counter_store()
assert type(store) is SQLiteSharedCounterStore,'Configured store must be production SQLite, never an in-memory fallback'
"""
COUNTER = """
count=store.increment('rollback-recovery-proof',3600)
ttl=store.ttl('rollback-recovery-proof')
assert ttl is not None and 0<ttl<=3600
print(count)
"""


def require_digest(image):
    if not re.fullmatch(r"[a-z0-9][a-z0-9./_:-]*@sha256:[0-9a-f]{64}", image):
        raise ValueError("Use the exact published backend image@sha256 digest")
    return image


def assert_counter(output, expected):
    assert output == str(expected), f"Shared counter lost cross-process/restart state: expected {expected}, observed {output!r}"


class OwnedDocker:
    def __init__(self):
        self.owner = secrets.token_hex(12)
        self.containers = []
        self.network = None
        self.hidden = []

    def redact(self, value):
        for secret in self.hidden:
            value = value.replace(secret, "[redacted]")
        return value

    def run(self, *args, timeout=45):
        try:
            result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Docker {args[0]} timed out") from None
        if result.returncode:
            raise RuntimeError(f"Docker {args[0]} failed: {self.redact(result.stderr[-4000:])}")
        return (result.stdout + result.stderr).strip() if args[0] == "logs" else result.stdout.strip()

    def create(self, name, image, *, alias, env=None):
        args = ["create", "--name", name, "--label", f"{LABEL}={self.owner}",
                "--network", self.network, "--network-alias", alias]
        for key, value in (env or {}).items():
            args.extend(["--env", f"{key}={value}"])
        # Intentionally no command arguments after the image: execute its CMD.
        identity = self.run(*args, image)
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise RuntimeError("Docker did not return an exact container ID")
        self.containers.append(identity)
        self.run("start", identity)
        return identity

    def cleanup(self):
        failures = []
        for kind, identity in [("container", item) for item in reversed(self.containers)] + (
                [("network", self.network)] if self.network else []):
            try:
                data = json.loads(self.run(kind, "inspect", identity))[0]
                labels = data["Config"].get("Labels", {}) if kind == "container" else data.get("Labels", {})
                if labels.get(LABEL) != self.owner:
                    raise RuntimeError("Refusing cleanup of an object without this run's ownership label")
                if kind == "container":
                    self.run("container", "rm", "--force", "--volumes", identity)
                else:
                    self.run("network", "rm", identity)
            except Exception as error:
                failures.append(self.redact(str(error)))
        if failures:
            raise RuntimeError("Owned cleanup failed: " + "; ".join(failures))


def until(check, *, seconds=90, description):
    deadline = time.monotonic() + seconds
    last = "condition false"
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (RuntimeError, ValueError, KeyError, AssertionError) as error:
            last = str(error)
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {description}: {last}")


def exercise(image, revision):
    require_digest(image)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected source revision must be a full Git commit")
    docker = OwnedDocker()
    backend = None
    try:
        docker.run("info", "--format", "{{.ServerVersion}}")
        docker.run("pull", image, timeout=180)
        config = json.loads(docker.run("image", "inspect", image))[0]["Config"]
        assert config["Cmd"] == DEFAULT_CMD, "Backend default CMD changed; review recovery contract"
        assert not config.get("Entrypoint"), "Unexpected backend entrypoint"
        assert config.get("Labels", {}).get("org.opencontainers.image.revision") == revision
        docker.run("pull", "postgres:17", timeout=180)
        docker.network = docker.run("network", "create", "--internal", "--label", f"{LABEL}={docker.owner}",
                                    "rollback-0150-" + docker.owner)
        password, jwt, signing = [secrets.token_hex(32) for _ in range(3)]
        docker.hidden = [password, jwt, signing]
        pg = docker.create("rollback-pg-" + docker.owner, "postgres:17", alias="pg", env={
            "POSTGRES_USER": "rollback_qa", "POSTGRES_PASSWORD": password, "POSTGRES_DB": "rollback_qa"})
        until(lambda: docker.run("exec", pg, "pg_isready", "-U", "rollback_qa", "-d", "rollback_qa"), description="owned PostgreSQL")
        backend = docker.create("rollback-backend-" + docker.owner, image, alias="backend", env={
            "ENV": "production", "DEBUG": "false", "STARTUP_SCHEMA_SYNC": "false", "RUN_SEED_ON_STARTUP": "false",
            "SEED_DEMO_USERS": "false", "SEED_SAMPLE_DATA": "false", "IMPORT_LEGACY_MODELS": "false",
            "DATABASE_URL": f"postgresql+psycopg2://rollback_qa:{password}@pg:5432/rollback_qa",
            "JWT_SECRET": jwt, "FILE_SIGNING_SECRET": signing, "SHARED_STORE_URL": COUNTER_URL,
            "SHARED_STORE_KEY_PREFIX": "rollback-0150-" + docker.owner,
            "CORS_ORIGINS": "https://rollback-qa.invalid", "FRONTEND_BASE_URL": "https://rollback-qa.invalid",
            "ERP_PUBLIC_BASE_URL": "https://rollback-qa.invalid", "TRUSTED_PROXY_CIDRS": "127.0.0.1/32",
            "FORWARDED_ALLOW_IPS": "", "WEB_CONCURRENCY": "2", "PORT": "10000",
        })

        def pids():
            return json.loads(docker.run("exec", backend, "python", "-c", WORKERS))

        marker = "startup: database migration head verified (" + HEAD + ")"

        def ready(minimum_startups):
            workers = pids()
            if len(workers) != 2:
                return False
            if docker.run("logs", backend).count(marker) < minimum_startups:
                return False
            docker.run("exec", backend, "python", "-c", PROBES)
            return workers

        first = until(lambda: ready(2), seconds=120, description="two strict production workers and both probes")
        docker.run("exec", backend, "python", "-c", STRICT)
        counters = []

        def increment(expected):
            # A new Python interpreter for every increment exercises the actual
            # configured store across independent processes, without host mounts.
            output = docker.run("exec", backend, "python", "-c", STRICT + COUNTER)
            assert_counter(output, expected)
            counters.append(expected)

        increment(1)
        increment(2)

        def verify_database():
            actual = docker.run("exec", pg, "psql", "-U", "rollback_qa", "-d", "rollback_qa", "-At", "-c",
                                "SELECT version_num FROM alembic_version; SELECT count(*) FROM package_customer_releases; SELECT count(*) FROM models; SELECT count(*) FROM users;")
            assert actual.splitlines() == [HEAD, "0", "0", "0"], "Unexpected schema head, release ledger, models or users"

        verify_database()
        before_kill = docker.run("logs", backend).count(marker)
        victim = first[0]
        assert victim > 1
        docker.run("exec", backend, "python", "-c",
                   "import os,signal;os.kill(" + str(victim) + ",signal.SIGKILL)")

        def recovered():
            workers = ready(before_kill + 1)
            return workers if workers and victim not in workers and len(set(workers) - set(first)) == 1 else False

        replacement = until(recovered, description="replacement child PID and fresh strict schema-0150 startup")
        increment(3)
        verify_database()
        before_restart = docker.run("logs", backend).count(marker)
        docker.run("restart", "--time", "15", backend)
        restarted = until(lambda: ready(before_restart + 2), seconds=120, description="container restart and two fresh schema-0150 workers")
        docker.run("exec", backend, "python", "-c", STRICT)
        increment(4)
        verify_database()
        print(json.dumps({"status": "PASS", "image": image, "revision": revision, "schema": HEAD,
                          "initial_worker_pids": first, "replacement_worker_pids": replacement,
                          "restarted_worker_pids": restarted, "ledger_rows": 0,
                          "shared_store": "SQLiteSharedCounterStore", "shared_counter_values": counters}))
    except Exception:
        if backend:
            print("Owned backend diagnostic logs:\n" + docker.redact(docker.run("logs", backend)[-6000:]))
        raise
    finally:
        docker.cleanup()


def self_test():
    good = "ghcr.io/example/backend@sha256:" + "a" * 64
    assert require_digest(good) == good
    for bad in ["backend:latest", "backend@sha256:bad", "-bad@sha256:" + "a" * 64]:
        try:
            require_digest(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Mutable or invalid image accepted")
    docker = OwnedDocker()
    docker.containers = ["a" * 64]
    calls = []
    with patch.object(docker, "run", side_effect=lambda *args, **kw: calls.append(args) or json.dumps([{"Config": {"Labels": {LABEL: "someone-else"}}}])):
        try:
            docker.cleanup()
        except RuntimeError as error:
            assert "without this run's ownership label" in str(error)
        else:
            raise AssertionError("Cleanup accepted foreign ownership")
    assert not any("rm" in command for command in calls)
    assert "alembic" in DEFAULT_CMD[-1] and "--workers ${WEB_CONCURRENCY:-2}" in DEFAULT_CMD[-1]
    for expected in (1, 2, 3, 4):
        assert_counter(str(expected), expected)
    try:
        assert_counter("1", 4)
    except AssertionError as error:
        assert "lost cross-process/restart state" in str(error)
    else:
        raise AssertionError("Counter reset after restart was accepted")
    # Stdlib-only challenge: the production validation snippet must refuse the
    # development in-memory fallback while still invoking both security guards.
    import os
    import sys
    from types import ModuleType, SimpleNamespace

    calls = []
    config = ModuleType("app.core.config")
    config.settings = SimpleNamespace(is_production=True, strict_security_required=True,
        STARTUP_SCHEMA_SYNC=False, GLOBAL_RATE_LIMIT_ENABLED=True, AUTH_MAX_FAILED_ATTEMPTS=5,
        AUTH_LOCKOUT_SECONDS=15, shared_store_url=COUNTER_URL,
        validate_runtime_security=lambda: calls.append("security"))
    proxy = ModuleType("app.core.proxy_trust")
    proxy.validate_proxy_runtime_configuration = lambda **kwargs: calls.append("proxy")
    shared = ModuleType("app.core.shared_store")

    class SQLiteSharedCounterStore:
        pass

    shared.SQLiteSharedCounterStore = SQLiteSharedCounterStore
    shared.get_shared_counter_store = lambda: object()
    modules = {"app": ModuleType("app"), "app.core": ModuleType("app.core"),
               "app.core.config": config, "app.core.proxy_trust": proxy, "app.core.shared_store": shared}
    with patch.dict(sys.modules, modules), patch.dict(os.environ, RUN_SEED_ON_STARTUP="false", WEB_CONCURRENCY="2"):
        try:
            exec(STRICT, {})
        except AssertionError as error:
            assert "in-memory fallback" in str(error)
        else:
            raise AssertionError("In-memory fallback accepted in production proof")
        shared.get_shared_counter_store = SQLiteSharedCounterStore
        exec(STRICT, {})
    assert calls == ["security", "proxy", "security", "proxy"]
    print("PASS: digest/default-CMD/owned cleanup, persisted counter/reset refusal, production SQLite type and security guards")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--revision")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.image and args.revision:
        exercise(args.image, args.revision)
    else:
        parser.error("--image and --revision are required")

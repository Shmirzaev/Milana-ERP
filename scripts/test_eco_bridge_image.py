"""CI-only actual default-CMD bridge proof on a private, disposable PostgreSQL.

Standard library + Docker only. Import never runs Docker. No host ports, mounts,
production config, credential adapter, business fixtures or automatic migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
import uuid

if not __debug__:
    raise RuntimeError("Optimized Python disables required disposable-image guards")

PREDECESSOR = "0150_package_customer_release"
SUCCESSOR = "0154_eco_receipt_details"
POSTGRES = "postgres@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
LABEL = "milana.eco.bridge.ci.owner"
TABLES = ("eco_material_batches", "eco_material_movements", "factory_fabric_transfers",
          "factory_fabric_transfer_lines", "eco_accessory_plans", "eco_accessory_requirements", "eco_accessory_allocations")
HTTP = """import json,urllib.request
for path in ('/health','/ready'):
 with urllib.request.urlopen('http://127.0.0.1:10000'+path,timeout=3) as response:
  assert response.status==200
  value=json.load(response)
  assert value['status']==('ok' if path=='/health' else 'ready')
  if path=='/ready':assert value['checks']['postgresql']=='ok'
print('healthy')
"""
SCHEMA_PROOF = """import json,sys
import sqlalchemy as sa
from app.db.session import engine
from app.db.eco_schema_compatibility import ECO_COLUMNS,accepts_eco_rollback_predecessor
revision=sys.argv[1]
with engine.connect() as db:
 db.execute(sa.text('SET TRANSACTION READ ONLY'))
 current=db.execute(sa.text('SELECT version_num FROM alembic_version')).scalar_one()
 assert current==revision
 accepted=accepts_eco_rollback_predecessor(db,{revision},{'0154_eco_receipt_details'})
 assert accepted==(revision=='0150_package_customer_release')
 inspector=sa.inspect(db)
 present=set(inspector.get_table_names()).intersection(ECO_COLUMNS)
 assert present==(set() if revision=='0150_package_customer_release' else set(ECO_COLUMNS))
 if present:
  for name in ('eco_material_batches','factory_fabric_transfer_lines'):
   column=next(c for c in inspector.get_columns(name) if c['name']=='receipt_details')
   assert isinstance(column['type'],sa.JSON) and not column['nullable'] and '{}' in column['default']
 assert db.execute(sa.text('SELECT count(*) FROM pg_index WHERE NOT indisvalid')).scalar_one()==0
 counts={name:db.execute(sa.text('SELECT count(*) FROM '+name)).scalar_one() for name in ('models','items','production_orders','stock_batches','packages','finished_goods_stock',*sorted(present))}
 assert not any(counts.values()),counts
 print(json.dumps(dict(revision=current,eco_tables=sorted(present),business_counts=counts)))
"""


class StartupError(RuntimeError):
    """A fatal log error must not be retried as incomplete worker readiness."""


class BridgeImageProof:
    def __init__(self, image, commit):
        assert re.fullmatch(r"ghcr\.io/shmirzaev/milana-erp-backend@sha256:[a-f0-9]{64}", image)
        assert re.fullmatch("[a-f0-9]{40}", commit)
        self.image, self.commit = image, commit
        self.owner = uuid.uuid4().hex
        self.prefix = "eco-bridge-ci-" + self.owner
        self.network = self.prefix + "-net"
        self.pg = self.prefix + "-pg"
        self.database = "eco_bridge_" + self.owner + "_qa"
        self.created = []
        self.network_intent = False
        password = secrets.token_hex(32)
        self.pg_env = dict(POSTGRES_DB=self.database, POSTGRES_USER="eco_qa", POSTGRES_PASSWORD=password,
                           PGDATA="/var/lib/postgresql/data/pgdata")
        self.env = dict(ENV="production", DEBUG="false", DATABASE_URL="postgresql+psycopg2://eco_qa:" + password + "@eco-qa-postgres:5432/" + self.database,
            JWT_SECRET=secrets.token_hex(48), FILE_SIGNING_SECRET=secrets.token_hex(48), RUN_SEED_ON_STARTUP="false", STARTUP_SCHEMA_SYNC="false",
            WEB_CONCURRENCY="2", DB_POOL_SIZE="8", DB_MAX_OVERFLOW="4", SEED_DEMO_USERS="false", SEED_SAMPLE_DATA="false", IMPORT_LEGACY_MODELS="false",
            BACKFILL_EMPLOYEES_FROM_USERS="false", SHARED_STORE_URL="sqlite:////tmp/eco-bridge-ci-counters.sqlite", SHARED_STORE_KEY_PREFIX="eco-bridge-ci",
            CORS_ORIGINS="http://127.0.0.1:10000", ERP_PUBLIC_BASE_URL="http://127.0.0.1:10000", FRONTEND_BASE_URL="http://127.0.0.1:10000",
            FORWARDED_ALLOW_IPS="", TRUSTED_PROXY_CIDRS="127.0.0.1/32", PORT="10000")

    def docker(self, *args, env=None, timeout=45):
        result = subprocess.run(["docker", *args], env=None if env is None else {**os.environ, **env},
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError("Disposable bridge Docker command failed: " + args[0])
        return result.stdout

    def inspect(self, kind, name):
        assert kind in ("container", "network"), "Unsupported disposable resource kind"
        result = subprocess.run(["docker", kind, "inspect", name], capture_output=True, text=True, timeout=20)
        if result.returncode:
            # Docker uses "network NAME not found" for network inspection,
            # while container inspection uses "No such container: NAME".
            # Match the entire diagnostic and requested resource, never a
            # substring that could hide daemon/permission or another-name errors.
            absent = {
                prefix + "No such " + resource + ": " + name
                for prefix in ("Error response from daemon: ", "Error: ")
                for resource in (kind, "object")
            }
            if kind == "network":
                absent.add("Error response from daemon: network " + name + " not found")
            assert (result.returncode == 1 and result.stdout.strip() in ("", "[]")
                    and result.stderr.strip() in absent), (
                "Cannot establish Docker resource absence: exit=" + str(result.returncode)
                + "; stderr=" + repr(result.stderr[:500]))
            return None
        return json.loads(result.stdout)[0]

    def owned(self, kind, name):
        value = self.inspect(kind, name)
        if value is not None:
            labels = (value["Config"].get("Labels") if kind == "container" else value.get("Labels")) or {}
            assert labels.get(LABEL) == self.owner, "Never touch a foreign resource"
        return value

    def remove(self, kind, name):
        value = self.owned(kind, name)
        if value is not None:
            self.docker(kind, "rm", *(["--force", "--volumes"] if kind == "container" else []), value["Id"])

    def start(self, name, image, values, extra=(), command=()):
        assert self.inspect("container", name) is None
        self.created.append(name)  # Record intent before Docker may time out.
        env_args = [arg for key in values for arg in ("--env", key)]
        self.docker("run", "--detach", "--name", name, "--label", LABEL + "=" + self.owner,
            "--restart", "no", "--network", self.network, "--pids-limit", "256", "--cpus", "1",
            "--memory", "512m" if name == self.pg else "1g", *extra, *env_args, image, *command, env=values)

    @staticmethod
    def wait_for(probe, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                return probe()
            except StartupError:
                raise
            except Exception:
                time.sleep(1)
        raise RuntimeError("Disposable bridge bounded readiness timed out")

    def migrate(self, revision):
        assert revision in (PREDECESSOR, SUCCESSOR)
        name = self.prefix + "-migration-" + revision[:4]
        command = "PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini upgrade " + revision
        self.start(name, self.image, self.env, ("--entrypoint", "sh"), ("-c", command))
        assert self.docker("wait", name, timeout=300).strip() == "0", "Explicit disposable migration failed"
        self.remove("container", name)

    def cold_start(self, revision, image):
        name = self.prefix + "-backend-" + revision[:4]
        self.start(name, self.image, self.env)  # No command/entrypoint override.
        marker = ("startup: verified empty ECO rollback predecessor accepted (" if revision == PREDECESSOR else "startup: database migration head verified (") + revision + ")"

        def fully_ready():
            self.docker("exec", name, "python", "-c", HTTP, timeout=10)
            workers = sum("spawn_main" in line for line in self.docker("top", name, "-eo", "pid,args").splitlines())
            output = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=20)
            assert output.returncode == 0
            logs = output.stdout + output.stderr
            if re.search(r"Traceback|CRITICAL|Exception", logs):
                raise StartupError("Fatal error in disposable bridge startup logs")
            assert workers == 2 and logs.count(marker) >= 2, "Both workers must finish strict startup"

        self.wait_for(fully_ready, 120)
        actual = self.owned("container", name)
        assert actual["Image"] == image["Id"]
        assert actual["Config"]["Cmd"] == image["Config"]["Cmd"]
        assert actual["Config"].get("Entrypoint") == image["Config"].get("Entrypoint")
        assert actual["State"]["Running"] and not actual["State"]["OOMKilled"] and actual["RestartCount"] == 0
        host = actual["HostConfig"]
        assert host["RestartPolicy"]["Name"] == "no" and not host["PortBindings"] and not host["PublishAllPorts"]
        assert not host.get("Binds") and not host.get("Privileged") and not actual.get("Mounts")
        assert host["Memory"] == 1073741824 and host["PidsLimit"] == 256
        assert set(actual["NetworkSettings"]["Networks"]) == {self.network}
        values = dict(item.split("=", 1) for item in actual["Config"]["Env"])
        assert all(values[key] == value for key, value in self.env.items())
        workers = sum("spawn_main" in line for line in self.docker("top", name, "-eo", "pid,args").splitlines())
        assert workers == 2
        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=20)
        logs = logs.stdout + logs.stderr
        assert logs.count(marker) >= 2 and not re.search(r"Traceback|CRITICAL|Exception", logs)
        schema = json.loads(self.docker("exec", name, "python", "-c", SCHEMA_PROOF, revision))
        result = dict(image=actual["Image"], revision=revision, workers=workers, marker_count=logs.count(marker),
                      logs_sha256=hashlib.sha256(logs.encode()).hexdigest(), schema=schema)
        self.remove("container", name)
        return result

    def run(self):
        proof = dict(commit=self.commit, image_reference=self.image, passed=False, phases=[])
        try:
            for reference in (self.image, POSTGRES):
                self.docker("pull", reference, timeout=180)
            image = json.loads(self.docker("image", "inspect", self.image))[0]
            pg_image = json.loads(self.docker("image", "inspect", POSTGRES))[0]
            assert self.image in image["RepoDigests"] and POSTGRES in pg_image["RepoDigests"]
            assert image["Config"]["Labels"]["org.opencontainers.image.revision"] == self.commit
            assert self.inspect("network", self.network) is None
            self.network_intent = True
            self.docker("network", "create", "--internal", "--label", LABEL + "=" + self.owner, self.network)
            network = self.owned("network", self.network)
            assert network["Internal"] and network["Driver"] == "bridge"
            self.start(self.pg, POSTGRES, self.pg_env,
                ("--network-alias", "eco-qa-postgres", "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,noexec,size=512m"),
                ("postgres", "-c", "max_connections=100", "-c", "shared_buffers=64MB"))
            self.wait_for(lambda: self.docker("exec", self.pg, "pg_isready", "-U", "eco_qa", "-d", self.database), 60)
            pg = self.owned("container", self.pg)
            assert not pg["HostConfig"]["PortBindings"] and not pg["HostConfig"]["PublishAllPorts"]
            for revision in (PREDECESSOR, SUCCESSOR):
                self.migrate(revision)
                proof["phases"].append(self.cold_start(revision, image))
            proof["passed"] = True
        finally:
            failures = []
            for name in reversed(self.created):
                try:
                    self.remove("container", name)
                except Exception as error:
                    failures.append(type(error).__name__)
            if self.network_intent:
                try:
                    self.remove("network", self.network)
                except Exception as error:
                    failures.append(type(error).__name__)
            if failures:
                raise RuntimeError("Owned disposable cleanup failed: " + ",".join(failures))
        return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    assert os.environ.get("GITHUB_ACTIONS") == "true", "This disposable gate is restricted to CI"
    assert os.environ.get("GITHUB_SHA") == args.commit, "CI source differs from requested image"
    print(json.dumps(BridgeImageProof(args.image, args.commit).run(), sort_keys=True))


if __name__ == "__main__":
    main()

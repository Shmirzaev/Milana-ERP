"""Admission safety and real PostgreSQL saturation/rollback in an isolated cluster."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("connection_budget", ROOT / "scripts/connection_budget.py")
budget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget)
POLICY = json.loads((ROOT / "deploy/connection-budget.json").read_text())


def state():
    return {
        "max_connections": 100, "superuser_reserved_connections": 3, "reserved_connections": 0,
        "roles": [{"name": n, "connection_limit": -1, "superuser": False, "connections": 0}
                  for n in POLICY["role_limits"]] +
                 [{"name": "postgres", "connection_limit": -1, "superuser": True, "connections": 0}],
    }


@pytest.mark.parametrize("fault", ["overbudget", "unknown", "busy", "privilege", "admin_name"])
def test_unsafe_budget_refused(fault):
    policy, live = deepcopy(POLICY), state()
    if fault == "overbudget":
        policy["role_limits"]["leadlens"] = 20
    elif fault == "unknown":
        live["roles"].append({"name": "new_service"})
    elif fault == "busy":
        live["roles"][0]["connections"] = 49
    elif fault == "privilege":
        live["roles"][0]["superuser"] = True
    else:
        policy["administrative_roles"] = ["postgres'; SELECT 1; --"]
    with pytest.raises(ValueError):
        budget.plan(policy, live)


def test_rollback_record_not_overwritten(tmp_path):
    path = tmp_path / "rollback.json"
    budget.save_exclusive(path, {"before": -1})
    with pytest.raises(FileExistsError):
        budget.save_exclusive(path, {"before": 48})
    assert json.loads(path.read_text()) == {"before": -1}


@pytest.fixture(scope="module")
def postgres(tmp_path_factory):
    psycopg2 = pytest.importorskip("psycopg2")
    binaries = Path(os.environ.get("OPS_TEST_PG_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
    if not (binaries / "initdb.exe").exists():
        pytest.skip("Set OPS_TEST_PG_BIN to isolated PostgreSQL test binaries")
    directory = tmp_path_factory.mktemp("budget-postgres")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    subprocess.run([str(binaries / "initdb.exe"), "-D", str(directory / "data"), "-U", "postgres",
                    "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, capture_output=True, timeout=60)
    options = f"-h 127.0.0.1 -p {port} -c max_connections=100 -c shared_buffers=16MB"
    subprocess.run([str(binaries / "pg_ctl.exe"), "-D", str(directory / "data"), "-l",
                    str(directory / "server.log"), "-o", options, "-w", "start"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    def connect(user="postgres"):
        return psycopg2.connect(host="127.0.0.1", port=port, dbname="postgres", user=user,
                                connect_timeout=5, application_name="ops02-isolated-capacity-test")
    psql = [str(binaries / "psql.exe"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres"]
    try:
        with connect() as admin, admin.cursor() as cursor:
            for role in POLICY["role_limits"]:
                cursor.execute(f'CREATE ROLE "{role}" LOGIN')
            cursor.execute("CREATE TABLE safety_marker(value text); INSERT INTO safety_marker VALUES ('unchanged')")
            cursor.execute("GRANT SELECT ON safety_marker TO erp")
        admin.close()
        yield connect, psql, directory
    finally:
        subprocess.run([str(binaries / "pg_ctl.exe"), "-D", str(directory / "data"), "-m", "fast", "-w", "stop"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def test_atomic_apply_full_capacity_and_rollback(postgres):
    connect, psql, directory = postgres
    before = budget.plan(POLICY, budget.snapshot(psql))
    record = directory / "rollback.json"
    command = [sys.executable, str(ROOT / "scripts/connection_budget.py"), "--policy",
               str(ROOT / "deploy/connection-budget.json"), "--psql-json", json.dumps(psql)]
    applied = subprocess.run([*command, "--apply", "--expected-plan-sha256", before["plan_sha256"],
                              "--rollback-record", str(record)], check=True, capture_output=True, text=True)
    assert json.loads(applied.stdout)["action"] == "applied"
    held = []
    try:
        for role, limit in POLICY["role_limits"].items():
            held.extend(connect(role) for _ in range(limit))
            with pytest.raises(Exception, match="too many connections for role"):
                connect(role)
        assert len(held) == 87
        # An extra local-only role represents ordinary maintenance admission.
        with connect() as admin, admin.cursor() as cursor:
            cursor.execute("CREATE ROLE ops_test_maintenance LOGIN")
        admin.close()
        held.extend(connect("ops_test_maintenance") for _ in range(10))
        with pytest.raises(Exception, match="remaining connection slots are reserved"):
            connect("ops_test_maintenance")
        held.extend(connect() for _ in range(3))
        assert len(held) == 100
        with pytest.raises(Exception, match="too many clients"):
            connect()
        for connection in held[-13:]:
            connection.close()
        del held[-13:]
        with connect() as admin, admin.cursor() as cursor:
            cursor.execute("DROP ROLE ops_test_maintenance")
        admin.close()
        restored = subprocess.run([*command, "--rollback", str(record)], check=True, capture_output=True, text=True)
        assert json.loads(restored.stdout)["action"] == "rolled_back"
        assert all(r["connection_limit"] == -1 for r in budget.snapshot(psql)["roles"])
        with held[0].cursor() as cursor:
            cursor.execute("SELECT value FROM safety_marker")
            assert cursor.fetchone() == ("unchanged",)
    finally:
        for connection in held:
            connection.close()


def test_limit_drift_aborts_whole_transaction(postgres):
    connect, psql, _ = postgres
    proposal = budget.plan(POLICY, budget.snapshot(psql))
    with connect() as admin, admin.cursor() as cursor:
        cursor.execute("ALTER ROLE leadlens CONNECTION LIMIT 7")
    admin.close()
    with pytest.raises(RuntimeError):
        budget.sql_json(psql, budget.transaction(POLICY, proposal["previous_limits"], POLICY["role_limits"]))
    actual = {r["name"]: r["connection_limit"] for r in budget.snapshot(psql)["roles"]}
    assert actual["leadlens"] == 7 and actual["erp"] == -1
    with connect() as admin, admin.cursor() as cursor:
        cursor.execute("ALTER ROLE leadlens CONNECTION LIMIT -1")
    admin.close()

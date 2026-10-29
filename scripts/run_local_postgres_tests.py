"""Run the default backend suite and S06 on disposable approved PostgreSQL."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from run_refactor_pg_gate import GROUPS, check_report, sanitized_pg_environment
from run_refactor_pg_supplement_gate import check_report as check_supplement, expected_nodeids, junit_nodeid

ROOT = Path(__file__).resolve().parents[1]
PORT = 55432
ADMIN_URL = f"postgresql+psycopg2://postgres@127.0.0.1:{PORT}/postgres"


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def require_local_docker() -> None:
    override = os.environ.get("DOCKER_HOST", "")
    endpoint = json.loads(docker("context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"))
    if (override and not override.startswith("unix://")) or not endpoint.startswith("unix://"):
        raise RuntimeError("PostgreSQL test runner requires a local Unix-socket Docker daemon")


def run_tests() -> int:
    # Reports remain available to the caller even if tests or gate validation fail.
    reports = ROOT / ".codex-work" / f"postgres-results-{secrets.token_hex(4)}"
    reports.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as scratch:
        env = sanitized_pg_environment(dict(os.environ), Path(scratch))
        results = []
        for label, cwd, nodes in (
            ("backend", ROOT / "backend", []),
            ("s06", ROOT, ["backend/tests/test_stock_adjustment_postgres.py"]),
        ):
            if label == "s06" and any(
                case.get("classname", "").endswith("test_stock_adjustment_postgres")
                for case in ET.parse(reports / "backend.xml").getroot().iter("testcase")
            ):
                continue
            report = reports / f"{label}.xml"
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-ra",
                                     *nodes, f"--junitxml={report}"], cwd=cwd, env=env)
            results.append(result.returncode)
        totals = {"passed": 0, "failed": 0, "skipped": 0}
        for report in reports.glob("*.xml"):
            for case in ET.parse(report).getroot().iter("testcase"):
                key = "skipped" if case.find("skipped") is not None else (
                    "failed" if any(case.find(tag) is not None for tag in ("failure", "error")) else "passed")
                totals[key] += 1
        print(json.dumps({"counts": totals, "reports": str(reports)}), flush=True)
        gate_failed = False
        try:
            tree = ET.parse(reports / "backend.xml")
            required = ET.Element("testsuite")
            for case in tree.getroot().iter("testcase"):
                if case.get("classname", "").rsplit(".", 1)[-1] in GROUPS:
                    required.append(case)
            required_report = reports / "required.xml"
            ET.ElementTree(required).write(required_report)
            counts = check_report(required_report)
            print(json.dumps({"required_pg_gate": "PASS", "groups": counts}), flush=True)
            selected = ET.Element("testsuite")
            wanted = set(expected_nodeids())
            for case in tree.getroot().iter("testcase"):
                node = junit_nodeid(case)
                if node in wanted:
                    selected.append(case)
            supplement = reports / "supplement.xml"
            ET.ElementTree(selected).write(supplement)
            supplement_result = check_supplement(supplement, list(wanted))
            print(json.dumps({"supplement_pg_gate": "PASS", "cases": supplement_result["case_count"]}), flush=True)
        except ValueError as exc:
            print(f"Required PostgreSQL gate FAIL: {exc}", flush=True)
            gate_failed = True
        return int(any(results) or gate_failed or totals["failed"] > 0 or totals["skipped"] > 0)


def main() -> int:
    if sys.argv[1:] == ["--inside"]:
        if not Path("/.dockerenv").is_file():
            raise RuntimeError("Internal test mode requires the disposable container")
        sys.path.insert(0, str(ROOT / "backend"))
        from app.tests.pg_approved_instance import load_approved_instance, verify_approved_instance

        instance = load_approved_instance()
        if instance.admin_dsn != ADMIN_URL or os.environ.get("MILANA_REQUIRE_TEST_PG") != "1":
            raise RuntimeError("Internal test mode requires this runner's loopback instance")
        for key in ("STABILIZATION_POSTGRES_URL", "S06_POSTGRES_URL", "PAYMENT_INTEGRITY_POSTGRES_URL"):
            if os.environ.get(key) != ADMIN_URL.rsplit("/", 1)[0] + "/milana_test":
                raise RuntimeError("Legacy test URLs must identify the disposable database")
        if os.environ.get("FN04_TEST_PG_ADMIN_URL") != ADMIN_URL:
            raise RuntimeError("Invoice test URL must identify the disposable instance")
        verify_approved_instance(instance)
        return run_tests()
    require_local_docker()
    name = f"milana-postgres-tests-{secrets.token_hex(4)}"
    image = f"{name}:local"
    started = image_built = False
    try:
        docker("run", "-d", "--rm", "--name", name,
               "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17-alpine",
               "postgres", "-h", "127.0.0.1", "-p", str(PORT))
        started = True
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1",
                               "-p", str(PORT), "-U", "postgres"], capture_output=True).returncode == 0:
                break
            time.sleep(1)
        else:
            raise TimeoutError("Disposable PostgreSQL did not become ready")
        for database in ("milana_test", "review_sales_list_local", "review_forecast_local"):
            docker("exec", name, "createdb", "-h", "127.0.0.1", "-p", str(PORT), "-U", "postgres", database)
        identity = json.loads(docker("exec", name, "psql", "-h", "127.0.0.1", "-p", str(PORT),
            "-U", "postgres", "-Atc", "SELECT json_build_object('server_version', current_setting('server_version'), "
            "'system_identifier', (SELECT system_identifier::text FROM pg_control_system()), "
            "'data_directory', current_setting('data_directory'))"))
        config = {**identity, "admin_dsn": ADMIN_URL, "host": "127.0.0.1", "port": PORT,
                  "target_prefix": "review_ci_refactor_"}
        subprocess.run(["docker", "build", "-q", "-t", image, str(ROOT / "backend")], check=True)
        image_built = True
        url = ADMIN_URL.rsplit("/", 1)[0] + "/milana_test"
        env = {"STABILIZATION_POSTGRES_URL": url, "S06_POSTGRES_URL": url,
               "FN04_TEST_PG_ADMIN_URL": ADMIN_URL, "PAYMENT_INTEGRITY_POSTGRES_URL": url,
               "DATABASE_URL": "sqlite:///:memory:", "ENV": "test",
               "SALES_LIST_REVIEW_URL": ADMIN_URL.rsplit("/", 1)[0] + "/review_sales_list_local",
               "FORECAST_CREATE_REVIEW_URL": ADMIN_URL.rsplit("/", 1)[0] + "/review_forecast_local",
               "MILANA_REQUIRE_TEST_PG": "1", "MILANA_TEST_PG_INSTANCE": json.dumps(config)}
        args = ["docker", "run", "--rm", "--user", "0", "--network", f"container:{name}",
                "-v", f"{ROOT}:/workspace", "-w", "/workspace"]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args += [image, "sh", "-c", "pip install -q -r backend/requirements-dev.txt && python scripts/run_local_postgres_tests.py --inside"]
        return subprocess.run(args).returncode
    finally:
        if started:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=True)
        if image_built:
            subprocess.run(["docker", "image", "rm", image], capture_output=True, check=True)


if __name__ == "__main__":
    raise SystemExit(main())

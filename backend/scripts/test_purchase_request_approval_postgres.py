"""Run the same seven approval tests on a newly owned loopback PostgreSQL DB.

The normal app/tests/conftest.py forces SQLite. Copy the exact test module to
an isolated temporary directory so this check cannot accidentally use SQLite.
Requires PUR_APPROVAL_PG_ADMIN_URL naming the loopback postgres admin database.
"""
from pathlib import Path
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import psycopg2
from psycopg2 import sql
from sqlalchemy.engine import make_url


def pool_checked_out(pool):
    """Return a pool's checked-out count when that pool exposes it."""
    method = getattr(pool, "checkedout", None)
    try:
        return int(method()) if callable(method) else None
    except Exception:
        return None


def owned_activity(cursor, database):
    """Inspect only the owned target; omit SQL, users, and client details."""
    cursor.execute("""SELECT pid, state, backend_type, application_name,
        EXTRACT(EPOCH FROM (clock_timestamp() - backend_start)),
        EXTRACT(EPOCH FROM (clock_timestamp() - xact_start))
        FROM pg_stat_activity WHERE datname = %s ORDER BY pid""", (database,))
    return [dict(pid=row[0], state=row[1], backend_type=row[2],
                 application_name_sha256=hashlib.sha256((row[3] or "").encode()).hexdigest(), backend_age_seconds=float(row[4]) if row[4] is not None else None,
                 transaction_age_seconds=float(row[5]) if row[5] is not None else None)
            for row in cursor.fetchall()]


def validate_fixture_evidence(evidence):
    keys = ("original_pool_before", "original_pool_after", "replacement_pool_after")
    if not isinstance(evidence, dict) or evidence.get("phase") != "fixture_dispose":
        raise ValueError("Invalid fixture disposal evidence")
    for key in keys:
        value = evidence.get(key, False)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Invalid fixture pool count")
    return evidence


def wait_owned_disconnect(cursor, database, timeout=2.0, poll=0.05):
    """Observe zero within deadline; statement timeouts bound each query separately."""
    start = time.monotonic()
    deadline = start + timeout
    attempts = 0
    initial = None
    remaining = None
    while True:
        before = time.monotonic()
        if before >= deadline:
            return {"initial": initial, "final": remaining, "attempts": attempts,
                    "elapsed_seconds": before - start, "timed_out": True}
        milliseconds = max(1, min(1000, int((deadline - before) * 1000)))
        cursor.execute("SELECT set_config('statement_timeout', %s, false)", (str(milliseconds),))
        cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (database,))
        remaining = cursor.fetchone()[0]
        attempts += 1
        if initial is None:
            initial = remaining
        now = time.monotonic()
        if now > deadline:
            return {"initial": initial, "final": remaining, "attempts": attempts,
                    "elapsed_seconds": now - start, "timed_out": True}
        if remaining == 0:
            return {"initial": initial, "final": 0, "attempts": attempts,
                    "elapsed_seconds": now - start, "timed_out": False}
        if now >= deadline:
            return {"initial": initial, "final": remaining, "attempts": attempts,
                    "elapsed_seconds": now - start, "timed_out": True}
        time.sleep(min(poll, deadline - now))


def cleanup_owned_target(cursor, database, report, timeout=2.0):
    """Attempt owned cleanup even when observation fails; unknown never passes."""
    observed = False
    try:
        report["disconnect"] = wait_owned_disconnect(cursor, database, timeout=timeout)
        observed = not report["disconnect"]["timed_out"] and report["disconnect"]["final"] == 0
        report["remaining"] = report["disconnect"]["final"]
        if not observed:
            try:
                report["activity"] = owned_activity(cursor, database)
            except Exception as error:
                report["activity_error_type"] = type(error).__name__
    except Exception as error:
        report["disconnect_error_type"] = type(error).__name__
    finally:
        # Restore a bounded admin statement timeout before attempting owned DROP.
        cursor.execute("SELECT set_config('statement_timeout', %s, false)", ("1000",))
        cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
        cursor.execute("SELECT count(*) FROM pg_database WHERE datname=%s", (database,))
        report["dropped"] = cursor.fetchone()[0] == 0
    if not report["dropped"] or not observed:
        raise RuntimeError("Owned PostgreSQL cleanup failed or tests leaked connections")


def main() -> int:
    admin_url = os.environ.get("PUR_APPROVAL_PG_ADMIN_URL")
    if not admin_url:
        raise RuntimeError("PUR_APPROVAL_PG_ADMIN_URL is required; this check must not skip")
    url = make_url(admin_url)
    if (url.drivername not in {"postgresql", "postgresql+psycopg2"}
            or url.host not in {"127.0.0.1", "::1"} or url.database != "postgres"
            or not url.port or url.query):
        raise RuntimeError("Require an explicit loopback PostgreSQL postgres URL and port, without query options")
    backend = Path(__file__).resolve().parents[1]
    source = backend / "app/tests/test_purchase_request_approval_operation.py"
    test_bytes = source.read_bytes()
    source_hash = hashlib.sha256(test_bytes).hexdigest()
    database = "review_pur_approve_" + secrets.token_hex(8)
    temporary_root = Path(tempfile.gettempdir()).resolve()
    temporary = temporary_root / ("milana-pur-approve-" + secrets.token_hex(12))
    # Exclusive Path.mkdir also avoids the Windows ACL issue with mkdtemp.
    temporary.mkdir(mode=0o777 if os.name == "nt" else 0o700)
    before_cwd = Path.cwd()
    admin = None
    created = False
    code = 1
    report = {"database": database, "test_sha256": source_hash, "created": False,
              "dropped": False, "passed": 0, "source_unchanged": False,
              "original_pool_before": None, "original_pool_after": None,
              "replacement_pool_after": None,
              "remaining": None, "activity": []}
    try:
        admin = psycopg2.connect(host=url.host, port=url.port, user=url.username,
                                password=url.password, dbname="postgres", connect_timeout=5, options="-c statement_timeout=1000")
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute("SELECT current_database(), inet_server_port(), host(inet_server_addr())")
            actual_db, actual_port, actual_host = cursor.fetchone()
            if actual_db != "postgres" or actual_port != url.port or not ipaddress.ip_address(actual_host).is_loopback:
                raise RuntimeError("PostgreSQL admin server identity is not the required loopback target")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        created = report["created"] = True
        test_url = url.set(database=database, drivername="postgresql+psycopg2")
        os.environ.update(DATABASE_URL=test_url.render_as_string(hide_password=False), ENV="test",
                          JWT_SECRET="disposable-pur-approval-test-secret",
                          FILE_SIGNING_SECRET="disposable-pur-approval-file-signing-secret",
                          SEED_SAMPLE_DATA="false", SEED_DEMO_USERS="false", STARTUP_SCHEMA_SYNC="false",
                          PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(backend))
        (temporary / "test_approval.py").write_bytes(test_bytes)
        (temporary / "conftest.py").write_text(
            "import json\nfrom pathlib import Path\nimport pytest\nfrom sqlalchemy import text\n"
            "from app.db.base import Base\nfrom app.db.session import engine\nimport app.schemas\n"
            "@pytest.fixture(scope='session', autouse=True)\n"
            "def owned_database():\n"
            "    assert engine.dialect.name == 'postgresql'\n"
            f"    assert engine.url.database == {database!r}\n"
            "    with engine.connect() as connection:\n"
            f"        assert connection.execute(text('SELECT current_database()')).scalar() == {database!r}\n"
            "    Base.metadata.create_all(engine)\n"
            "    yield\n"
            "    def checked_out(pool):\n"
            "        method = getattr(pool, 'checkedout', None)\n"
            "        try:\n"
            "            return int(method()) if callable(method) else None\n"
            "        except Exception:\n"
            "            return None\n"
            "    original_pool = engine.pool\n"
            "    before = checked_out(original_pool)\n"
            "    engine.dispose()\n"
            "    Path('fixture-dispose.json').write_text(json.dumps({'phase': 'fixture_dispose', "
            "'original_pool_before': before, 'original_pool_after': checked_out(original_pool), "
            "'replacement_pool_after': checked_out(engine.pool)}), encoding='utf-8')\n", encoding="utf-8")
        os.chdir(temporary)
        import pytest
        code = int(pytest.main([str(temporary / "test_approval.py"), "--confcutdir=" + str(temporary),
                               "-q", "-p", "no:cacheprovider", "--tb=short",
                               "--junitxml=" + str(temporary / "tests.xml")]))
        fixture_evidence = json.loads((temporary / "fixture-dispose.json").read_text(encoding="utf-8"))
        validate_fixture_evidence(fixture_evidence)
        suite = ET.parse(temporary / "tests.xml").getroot().find("testsuite")
        cases = suite.findall("testcase") if suite is not None else []
        if (suite is None or len(cases) != 7
                or any(int(suite.attrib[key]) for key in ("failures", "errors", "skipped"))
                or not any(case.attrib["name"] == "test_approval_all_mapped_writes_are_schema_owned_and_one_session"
                           for case in cases)):
            raise RuntimeError("All seven approval cases, including the mapped-write guard, must pass without skips")
        report["passed"] = len(cases)
    finally:
        try:
            fixture_file = temporary / "fixture-dispose.json"
            if fixture_file.is_file():
                try:
                    report["fixture_dispose"] = validate_fixture_evidence(json.loads(fixture_file.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    report["fixture_dispose_error"] = True
            session_module = sys.modules.get("app.db.session")
            if session_module is not None:
                original_pool = session_module.engine.pool
                report["original_pool_before"] = pool_checked_out(original_pool)
                session_module.engine.dispose()
                report["original_pool_after"] = pool_checked_out(original_pool)
                report["replacement_pool_after"] = pool_checked_out(session_module.engine.pool)
            if created and admin is not None:
                with admin.cursor() as cursor:
                    cleanup_owned_target(cursor, database, report)
        finally:
            if admin is not None:
                admin.close()
            os.chdir(before_cwd)
            if temporary.parent != temporary_root or not temporary.name.startswith("milana-pur-approve-") or temporary.is_symlink():
                raise RuntimeError("Unexpected temporary cleanup target")
            try:
                shutil.rmtree(temporary)
            finally:
                report["source_unchanged"] = hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
                print(json.dumps(report))
    if not report["source_unchanged"] or not report["dropped"] or report["passed"] != 7:
        raise RuntimeError("Approval PostgreSQL verification did not complete")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

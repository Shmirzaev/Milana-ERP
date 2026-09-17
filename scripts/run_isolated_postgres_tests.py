"""Run opt-in regression tests on a new disposable local PostgreSQL cluster.

Usage: python scripts/run_isolated_postgres_tests.py --pg-bin PATH [pytest args]
Never uses an existing server, application .env or production data.
"""
import argparse
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    args, tests = parser.parse_known_args()
    repo = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix="milana-fix-postgres-"))
    data = scratch / "data"
    password = secrets.token_hex(24)
    password_file = scratch / "password.tmp"
    password_file.write_text(password, encoding="ascii")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    suffix = ".exe" if os.name == "nt" else ""

    def command(name, *values):
        # Files prevent the Windows server process inheriting captured pipes.
        with (scratch / f"{name}.log").open("a", encoding="utf-8") as log:
            result = subprocess.run([str(args.pg_bin / (name + suffix)), *map(str, values)],
                                    stdout=log, stderr=log, timeout=60)
        if result.returncode:
            raise RuntimeError(f"{name} failed; inspect local logs in {scratch}")

    started = False
    try:
        command("initdb", "-D", data, "-U", "erp_test", "--pwfile", password_file,
                "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C")
        password_file.unlink()
        started = True
        command("pg_ctl", "-D", data, "-l", scratch / "server.log", "-o",
                f"-h 127.0.0.1 -p {port} -c shared_buffers=32MB -c max_connections=16 "
                "-c work_mem=2MB -c statement_timeout=20000 -c lock_timeout=15000", "-w", "start")
        env = dict(os.environ)
        for key in list(env):
            if key.startswith(("PG", "DATABASE_", "SMTP_", "RESEND_", "REDIS_", "SHARED_STORE_", "INTEGRATION_", "ATTENDANCE_")):
                env.pop(key)
        url = f"postgresql+psycopg2://erp_test:{password}@127.0.0.1:{port}/postgres"
        env.update(PAYMENT_INTEGRITY_POSTGRES_URL=url, STABILIZATION_POSTGRES_URL=url,
                   DATABASE_URL="sqlite:///:memory:", ENV="test", RUN_SEED_ON_STARTUP="false",
                   STARTUP_SCHEMA_SYNC="false", SHARED_STORE_URL="", REDIS_URL="", SMTP_HOST="",
                   RESEND_API_KEY="", AI_MONITOR_PASSWORD="", PYTHONDONTWRITEBYTECODE="1")
        env["PYTHONPATH"] = str(repo / "backend")
        # Run outside the checkout so settings cannot load a developer's .env.
        # Resolve existing test paths while preserving pytest options/filters.
        isolated_tests = []
        for value in tests:
            path, separator, node = value.partition("::")
            candidate = repo / "backend" / path
            isolated_tests.append(str(candidate.resolve()) + separator + node if candidate.exists() else value)
        if not tests:
            isolated_tests = [str(repo / "backend" / "app" / "tests")]
        print(f"Disposable PostgreSQL: 127.0.0.1:{port}; synthetic schemas only", flush=True)
        result = subprocess.run([sys.executable, "-m", "pytest", *isolated_tests], cwd=scratch, env=env)
        return result.returncode
    finally:
        if password_file.exists():
            password_file.unlink()
        if started:
            command("pg_ctl", "-D", data, "-m", "fast", "-w", "stop")
            print(f"Disposable cluster stopped; local diagnostic files retained: {scratch}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

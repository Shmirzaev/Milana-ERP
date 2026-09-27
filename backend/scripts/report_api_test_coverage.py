"""Optional local TestClient traffic ledger; never a correctness/branch-coverage claim.

From backend/:
  python scripts/report_api_test_coverage.py run --output batch.json -- app/tests/test_auth.py -q
  python scripts/report_api_test_coverage.py merge --output merged.json batch.json other.json

Only explicit app/tests/*.py targets are accepted. The existing conftest must
initialize its temporary SQLite engine. An application .env is refused without
reading it. Pytest terminal output is suppressed to keep payloads/credentials out
of this command's output; the pytest exit code and aggregate outcomes are retained.
This is an observer, not a sandbox for arbitrary test code or subprocesses.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Lock
from unittest.mock import patch
from uuid import uuid4


WARNING = "Observed TestClient traffic only; not proof of assertions, authorization, branches, concurrency, or business correctness."


def source_state(directory):
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=directory, stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=directory, stderr=subprocess.DEVNULL))
        return {"source_revision": revision, "source_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"source_revision": None, "source_dirty": None}


def configure_test_environment(environment):
    prefixes = ("PG", "DATABASE_", "SMTP_", "RESEND_", "REDIS_", "SHARED_STORE_", "INTEGRATION_", "ATTENDANCE_", "AI_MONITOR_")
    names = {
        "STABILIZATION_POSTGRES_URL", "PAYMENT_INTEGRITY_POSTGRES_URL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "SPACE_ID", "SPACE_HOST", "HF_SPACE_ID", "HF_SPACE_HOST", "RENDER", "RENDER_EXTERNAL_HOSTNAME", "VERCEL", "PUBLIC_DEPLOYMENT",
    }
    for key in list(environment):
        if key.upper().startswith(prefixes) or key.upper() in names:
            environment.pop(key)
    environment.update(
        DATABASE_URL="sqlite:///:memory:", ENV="test", SMTP_HOST="", RESEND_API_KEY="", REDIS_URL="", SHARED_STORE_URL="",
        AI_MONITOR_PASSWORD="", RUN_SEED_ON_STARTUP="false", STARTUP_SCHEMA_SYNC="false",
        ERP_PUBLIC_BASE_URL="http://127.0.0.1", FRONTEND_BASE_URL="http://127.0.0.1",
    )


def _require_loopback(host):
    if host in ("localhost", b"localhost"):
        return
    try:
        if ipaddress.ip_address(host.decode("ascii") if isinstance(host, bytes) else host).is_loopback:
            return
    except (ValueError, UnicodeError):
        pass
    raise RuntimeError("Non-loopback network access is disabled for the coverage run")


@contextmanager
def loopback_sockets_only():
    """Guard Python sockets; not a security sandbox for native clients/subprocesses."""
    resolve, connect, connect_ex, sendto = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto

    def guarded_resolve(host, *args, **kwargs):
        _require_loopback(host)
        results = resolve(host, *args, **kwargs)
        for result in results:
            _require_loopback(result[4][0])
        return results

    def check_address(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            _require_loopback(address[0])

    def guarded_connect(sock, address):
        check_address(sock, address)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        check_address(sock, address)
        return connect_ex(sock, address)

    def guarded_sendto(sock, data, *args):
        check_address(sock, args[-1])
        return sendto(sock, data, *args)

    with ExitStack() as stack:
        for owner, name, replacement in (
            (socket, "getaddrinfo", guarded_resolve), (socket.socket, "connect", guarded_connect),
            (socket.socket, "connect_ex", guarded_connect_ex), (socket.socket, "sendto", guarded_sendto),
        ):
            stack.enter_context(patch.object(owner, name, replacement))
        yield


def route_inventory(app, prefix=""):
    from fastapi.routing import APIRoute
    from starlette.routing import Mount

    entries = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            entries.extend((method, prefix + route.path, route) for method in sorted(route.methods or ()))
        elif isinstance(route, Mount) and hasattr(route.app, "routes"):
            entries.extend(route_inventory(route.app, prefix + route.path))
    return entries


def _matched_key(app, scope, prefix=""):
    from fastapi.routing import APIRoute
    from starlette.routing import Match, Mount

    for route in app.routes:
        match, child = route.matches(scope)
        if match == Match.FULL:
            if isinstance(route, APIRoute):
                return scope["method"], prefix + route.path
            if isinstance(route, Mount) and hasattr(route.app, "routes"):
                return _matched_key(route.app, {**scope, **child}, prefix + route.path)
            return None
    return None


def _empty_counts():
    return {"requests": 0, "statuses": {}, "exceptions": 0, "dispatched": 0, "before_dispatch": 0}


class TrafficLedger:
    def __init__(self, app):
        self.app = app
        entries = route_inventory(app)
        self.inventory = sorted({(method, path) for method, path, _ in entries})
        self.route_ids = {id(route) for _, _, route in entries}
        self.observations = {key: _empty_counts() for key in self.inventory}
        self.unattributed = _empty_counts()
        self.lock = Lock()

    def observe(self, scope, status, exception, request_scope=None):
        # Router matching never stores concrete paths, parameters, query strings,
        # headers, bodies, exception messages, test names, or actor identifiers.
        key = _matched_key(self.app, request_scope or scope)
        dispatched = id(scope.get("route")) in self.route_ids
        with self.lock:
            counts = self.observations.get(key, self.unattributed)
            counts["requests"] += 1
            counts["exceptions"] += int(exception)
            counts["dispatched" if dispatched else "before_dispatch"] += 1
            if status is not None:
                code = str(status)
                counts["statuses"][code] = counts["statuses"].get(code, 0) + 1

    def report(self, *, run_id=None, pytest_exit_code=0, test_outcomes=None, source_revision=None, source_dirty=None):
        with self.lock:
            run = {
                "id": run_id or uuid4().hex, "pytest_exit_code": int(pytest_exit_code),
                "source_revision": source_revision, "source_dirty": source_dirty,
                "test_outcomes": dict(test_outcomes or {}),
                "observations": [
                    {"method": key[0], "path": key[1], **counts}
                    for key, counts in self.observations.items() if counts["requests"]
                ],
                "unattributed": self.unattributed,
            }
            # Detach mutable counters before a later request or merge.
            return build_report(self.inventory, [json.loads(json.dumps(run))])


class ObservedApp:
    def __init__(self, app, ledger):
        self.app, self.ledger = app, ledger

    def __getattr__(self, name):
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status = None
        exception = False
        request_scope = {key: scope[key] for key in ("type", "method", "path", "root_path") if key in scope}

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        except BaseException:
            exception = True
            raise
        finally:
            self.ledger.observe(scope, status, exception, request_scope)


def _clean_counts(value):
    counts = _empty_counts()
    for field in ("requests", "exceptions", "dispatched", "before_dispatch"):
        number = value.get(field, 0)
        if type(number) is not int or number < 0:
            raise ValueError("Invalid ledger counter")
        counts[field] = number
    for code, number in value.get("statuses", {}).items():
        if not str(code).isdigit() or not 100 <= int(code) <= 599 or type(number) is not int or number < 0:
            raise ValueError("Invalid ledger status counter")
        counts["statuses"][str(int(code))] = number
    if sum(counts["statuses"].values()) > counts["requests"]:
        raise ValueError("Status count exceeds request count")
    if counts["exceptions"] > counts["requests"]:
        raise ValueError("Exception count exceeds request count")
    if counts["dispatched"] + counts["before_dispatch"] != counts["requests"]:
        raise ValueError("Dispatch counts do not match request count")
    return counts


def _add_counts(target, source):
    for field in ("requests", "exceptions", "dispatched", "before_dispatch"):
        target[field] += source[field]
    target["statuses"] = dict(Counter(target["statuses"]) + Counter(source["statuses"]))


def build_report(inventory, runs):
    inventory = sorted(set(tuple(key) for key in inventory))
    totals = {key: _empty_counts() for key in inventory}
    unattributed = _empty_counts()
    unique_runs = {}
    for raw in runs:
        run = {
            "id": str(raw["id"]), "pytest_exit_code": int(raw["pytest_exit_code"]),
            "source_revision": raw.get("source_revision"), "source_dirty": raw.get("source_dirty"),
            "test_outcomes": {key: int(raw.get("test_outcomes", {}).get(key, 0)) for key in ("passed", "failed", "skipped")},
            "observations": [], "unattributed": _clean_counts(raw["unattributed"]),
        }
        if len(run["id"]) != 32 or any(char not in "0123456789abcdef" for char in run["id"]):
            raise ValueError("Invalid run identity")
        revision = run["source_revision"]
        if revision is not None and (not isinstance(revision, str) or len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision)):
            raise ValueError("Invalid source revision")
        if run["source_dirty"] is not None and type(run["source_dirty"]) is not bool:
            raise ValueError("Invalid source dirty marker")
        seen = set()
        for observation in raw["observations"]:
            key = observation["method"], observation["path"]
            if key not in totals or key in seen:
                raise ValueError("Unknown or duplicate observation route")
            seen.add(key)
            run["observations"].append({"method": key[0], "path": key[1], **_clean_counts(observation)})
        run["observations"].sort(key=lambda row: (row["method"], row["path"]))
        if run["id"] in unique_runs:
            if run != unique_runs[run["id"]]:
                raise ValueError("Conflicting data for the same run")
            continue
        unique_runs[run["id"]] = run
        _add_counts(unattributed, run["unattributed"])
        for row in run["observations"]:
            _add_counts(totals[row["method"], row["path"]], row)
    routes = []
    for (method, path), counts in totals.items():
        classes = {int(code) // 100 for code in counts["statuses"]}
        categories = [name for code, name in ((2, "success"), (3, "redirect"), (4, "rejection"), (5, "server_error")) if code in classes]
        if counts["exceptions"]:
            categories.append("exception")
        routes.append({"method": method, "path": path, "categories": categories or ["unhit" if not counts["requests"] else "other"], **counts})
    return {
        "schema_version": 1,
        "inventory_sha256": hashlib.sha256(json.dumps(inventory, separators=(",", ":")).encode()).hexdigest(),
        "warning": WARNING,
        "scope": "Unique FastAPI HTTP method/route patterns, including mounted FastAPI apps. Observes newly constructed TestClient instances for the conftest app only; excludes docs, static mounts, WebSockets, other wrappers/clients and direct service calls.",
        "confidence": "HTTP status observation only. Dispatched means route selection, not endpoint-function execution; before_dispatch is inferred router attribution. Unhit means unobserved in these batches. Merge checks route inventory, not implementation equivalence; dirty runs are not exact revision evidence.",
        "performance": "Complexity and instrumentation overhead have not been measured.",
        "summary": {
            "endpoints": len(routes), "observed": sum(row["requests"] > 0 for row in routes),
            "success": sum("success" in row["categories"] for row in routes),
            "rejection": sum("rejection" in row["categories"] for row in routes),
            "unhit": sum(not row["requests"] for row in routes),
            "requests": sum(row["requests"] for row in routes) + unattributed["requests"],
            "matched_requests": sum(row["requests"] for row in routes), "runs": len(unique_runs),
            "failed_runs": sum(run["pytest_exit_code"] != 0 for run in unique_runs.values()),
            "source_revisions": sorted({run["source_revision"] for run in unique_runs.values() if run["source_revision"]}),
            "dirty_runs": sum(run["source_dirty"] is True for run in unique_runs.values()),
            "unknown_source_runs": sum(run["source_revision"] is None or run["source_dirty"] is None for run in unique_runs.values()),
        },
        "routes": routes, "unattributed": unattributed, "runs": list(unique_runs.values()),
    }


def merge_reports(reports):
    if not reports:
        raise ValueError("At least one report is required")
    inventory = [(row["method"], row["path"]) for row in reports[0]["routes"]]
    expected = build_report(inventory, [])["inventory_sha256"]
    runs = []
    for report in reports:
        keys = [(row["method"], row["path"]) for row in report["routes"]]
        if report.get("schema_version") != 1 or build_report(keys, [])["inventory_sha256"] != expected:
            raise ValueError("Cannot merge different schema versions or route inventories")
        runs.extend(report["runs"])
    return build_report(inventory, runs)


class CoveragePlugin:
    def __init__(self):
        self.ledger = None
        self.client_patch = None
        self.outcomes = {}

    def pytest_sessionstart(self, session):
        from app.tests import conftest
        from app.db import session as database
        from starlette.testclient import TestClient

        engine = conftest.test_engine
        if engine.dialect.name != "sqlite" or database.engine is not engine or not Path(engine.url.database).parent.name.startswith("erp-test-"):
            raise RuntimeError("Coverage requires the existing temporary SQLite test fixture")
        target = conftest.app
        self.ledger = TrafficLedger(target)
        original = TestClient.__init__
        ledger = self.ledger

        def initialize(client, app, *args, **kwargs):
            return original(client, ObservedApp(app, ledger) if app is target else app, *args, **kwargs)

        self.client_patch = patch.object(TestClient, "__init__", initialize)
        self.client_patch.start()

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.failed or report.skipped:
            identity = hashlib.sha256(report.nodeid.encode()).digest()
            severity = {"passed": 0, "skipped": 1, "failed": 2}
            previous = self.outcomes.get(identity, "passed")
            self.outcomes[identity] = max(previous, report.outcome, key=severity.get)

    def pytest_unconfigure(self, config):
        if self.client_patch:
            self.client_patch.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("pytest_args", nargs=argparse.REMAINDER)
    merge = commands.add_parser("merge")
    merge.add_argument("--output", required=True, type=Path)
    merge.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    exit_code = 0
    if args.command == "merge":
        try:
            report = merge_reports([json.loads(path.read_text(encoding="utf-8")) for path in args.reports])
        except (KeyError, TypeError, ValueError):
            parser.error("Invalid report data, conflicting run identities, or incompatible route inventories")
    else:
        backend = Path(__file__).resolve().parents[1]
        if (backend / ".env").exists():
            parser.error("Refusing to run beside an application .env; use the clean synthetic test worktree")
        test_args = args.pytest_args
        if test_args[:1] == ["--"]:
            test_args = test_args[1:]
        if not any(arg.startswith("app/tests/test_") and ".py" in arg for arg in test_args):
            parser.error("Select explicit app/tests/test_*.py files; no implicit full-suite run")
        if "app.core.config" in sys.modules:
            parser.error("Run as a fresh standalone process, before application settings are imported")
        os.chdir(backend)
        sys.path.insert(0, str(backend))
        configure_test_environment(os.environ)
        source = source_state(backend)
        import pytest

        plugin = CoveragePlugin()
        with open(os.devnull, "w", encoding="utf-8") as quiet, redirect_stdout(quiet), redirect_stderr(quiet), loopback_sockets_only():
            exit_code = int(pytest.main(test_args, plugins=[plugin]))
        if plugin.ledger is None:
            parser.error("Test fixture initialization failed; no coverage report was generated")
        report = plugin.ledger.report(pytest_exit_code=exit_code, test_outcomes=Counter(plugin.outcomes.values()), **source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    result = {"summary": report["summary"], "warning": WARNING}
    if args.command == "run":
        result["pytest_exit_code"] = exit_code
    else:
        result["input_pytest_exit_codes"] = sorted({run["pytest_exit_code"] for run in report["runs"]})
    print(json.dumps(result))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

"""Required isolated refactor PG checks; skips and missing case groups fail.

This runs only with an explicitly supplied approved-instance record. It never
discovers a local server or creates that record from an arbitrary endpoint.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


# Minimum collected counts pin the current parameterized business cases. Adding
# cases is allowed; removing a required case needs an explicit ledger change.
GROUPS = {
    "test_customer_create_postgres": (6, ("test_pg_route_saves_all_fields_and_audit_same_session", "test_pg_route_refuses_unauthenticated_and_forbidden_without_writes", "test_pg_route_failure_rolls_back_then_retry", "test_pg_concurrent_customers_keep_audit_chain")),
    "test_brand_create_postgres": (2, ("test_pg_create_duplicate_and_audit", "test_pg_audit_failure_rolls_back_then_retry")),
    "test_planning_alternate_creation_postgres": (5, ()),
    "test_purchase_conversion_postgres": (7, ()),
    "test_bom_add_characterization": (54, ()),
    "test_forecast_review_postgres": (9, ()),
    "test_stock_movement_and_reservation_postgres": (7, ()),
    "test_sales_update_old_behavior": (4, (
        "test_pg_stale_unchanged_status_cannot_rewind_concurrent_workflow",
        "test_pg_edit_and_audit_rollback_together_then_retry",
        "test_pg_unknown_customer_fails_fk_atomically_without_custom_service_refusal",
    )),
    "test_finance_sales_invoice_generation": (5, (
        "test_sales_generation_pg_failure_rolls_back_invoice_and_audit_then_retry",
        "test_sales_generation_pg_serializes_two_issuers_of_one_order",
        "test_sales_generation_pg_and_manual_entry_points_share_one_invoice",
    )),
    "test_invoice_creation_integrity": (4, (
        "test_concurrent_same_entry_point_creates_exactly_one_invoice",
        "test_concurrent_mixed_entry_points_create_exactly_one_invoice",
        "test_concurrent_creation_does_not_duplicate_invoice_numbers",
    )),
    "test_customer_invoice_creation_race": (10, ()),
}
REQUIRED_CASES = json.loads(
    Path(__file__).with_name("refactor_pg_required_cases.json").read_text(encoding="utf-8")
)["cases"]


def required_nodes() -> list[str]:
    result = []
    for module, (_, names) in GROUPS.items():
        path = f"app/tests/{module}.py"
        if names:
            result.extend(f"{path}::{name}" for name in names)
        else:
            result.append(path)
    return result


def check_report(report: Path) -> dict[str, int]:
    cases = list(ET.parse(report).getroot().iter("testcase"))
    if not cases:
        raise ValueError("required PG gate produced no test cases")
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    if len(set(identities)) != len(identities):
        raise ValueError("required PG report contains duplicate case identities")
    for case in cases:
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error")):
            raise ValueError(f"required PG case did not pass: {case.get('classname')}.{case.get('name')}")
    counts = {}
    for module, (minimum, names) in GROUPS.items():
        selected = [case for case in cases if case.get("classname", "").split(".")[-1] == module]
        counts[module] = len(selected)
        if len(selected) < minimum:
            raise ValueError(f"required PG group {module}: {len(selected)} cases, expected at least {minimum}")
        for name in names:
            if not any(case.get("name", "").split("[", 1)[0] == name for case in selected):
                raise ValueError(f"required PG function missing: {module}.{name}")
        actual_names = {case.get("name", "") for case in selected}
        missing = set(REQUIRED_CASES[module]) - actual_names
        if missing:
            raise ValueError(f"required PG case identities missing in {module}: {sorted(missing)}")
    return counts


def configure_ci(identity_path: Path, env_path: Path) -> None:
    """Use identity read through docker exec in the just-created CI container.

    The published endpoint is fixed, loopback-only, in this ephemeral Linux job;
    the fixture checks it matches the independently inspected container before DDL.
    This command does not connect to a database or authorize a workstation server.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("CI bootstrap is restricted to GitHub Actions")
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if (not str(identity["system_identifier"]).isdecimal()
            or not str(identity["server_version"]).startswith("17.")
            or not str(identity["data_directory"]).startswith("/")):
        raise ValueError("unexpected CI container identity")
    config = {
        "admin_dsn": "postgresql+psycopg2://postgres@127.0.0.1:55432/postgres",
        "host": "127.0.0.1", "port": 55432,
        "server_version": identity["server_version"],
        "system_identifier": str(identity["system_identifier"]),
        "data_directory": identity["data_directory"],
        "target_prefix": "review_ci_refactor_",
    }
    with env_path.open("a", encoding="utf-8") as output:
        output.write("MILANA_REQUIRE_TEST_PG=1\n")
        output.write("MILANA_TEST_PG_INSTANCE=" + json.dumps(config, separators=(",", ":")) + "\n")


def sanitized_pg_environment(source: dict[str, str], scratch: Path) -> dict[str, str]:
    """Remove inherited libpq configuration; use only empty owned config files."""
    env = {key: value for key, value in source.items() if not key.upper().startswith("PG")}
    for key, filename in (("PGPASSFILE", "pgpass"), ("PGSERVICEFILE", "pgservice")):
        path = scratch / filename
        path.write_text("", encoding="utf-8")
        env[key] = str(path)
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci-identity", type=Path)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--report", type=Path, default=Path("refactor-pg-gate.xml"))
    args = parser.parse_args()
    if args.ci_identity:
        if not args.github_env:
            parser.error("--ci-identity requires --github-env")
        configure_ci(args.ci_identity, args.github_env)
        return 0
    if os.environ.get("MILANA_REQUIRE_TEST_PG") != "1" or not os.environ.get("MILANA_TEST_PG_INSTANCE"):
        parser.error("required PG gate needs MILANA_REQUIRE_TEST_PG=1 and explicit approved instance")
    report = args.report.resolve()
    # Never accept a stale report after a failed or interrupted pytest process.
    if report.exists():
        parser.error("report path already exists; choose a fresh report path")
    backend = Path(__file__).resolve().parents[1] / "backend"
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               *required_nodes(), f"--junitxml={report}"]
    with tempfile.TemporaryDirectory(prefix="milana-pg-env-") as scratch:
        env = sanitized_pg_environment(dict(os.environ), Path(scratch))
        completed = subprocess.run(command, cwd=backend, check=False, timeout=1800, env=env)
    if completed.returncode:
        return completed.returncode
    counts = check_report(report)
    print(json.dumps({"required_pg_gate": "PASS", "passed_case_counts": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

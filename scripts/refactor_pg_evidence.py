"""Reusable evidence bodies for the existing PostgreSQL verification runners.

The primary and supplemental runners supply their own unchanged gate policies.
CLI arguments, process execution and resource ownership stay with each launcher.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET


def check_required_report(report: Path, groups: dict, required_cases: dict) -> dict[str, int]:
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
    for module, (minimum, names) in groups.items():
        selected = [case for case in cases if case.get("classname", "").split(".")[-1] == module]
        counts[module] = len(selected)
        if len(selected) < minimum:
            raise ValueError(f"required PG group {module}: {len(selected)} cases, expected at least {minimum}")
        for name in names:
            if not any(case.get("name", "").split("[", 1)[0] == name for case in selected):
                raise ValueError(f"required PG function missing: {module}.{name}")
        actual_names = {case.get("name", "") for case in selected}
        missing = set(required_cases[module]) - actual_names
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


def junit_nodeid(case: ET.Element) -> str:
    module = case.get("classname", "").rsplit(".", 1)[-1]
    name = case.get("name", "")
    if not module or not name:
        raise ValueError("JUnit case is missing classname or name")
    return f"backend/app/tests/{module}.py::{name}"


def check_supplement_report(report: Path, expected: list[str], expected_count: int) -> dict[str, object]:
    root = ET.parse(report).getroot()
    cases = list(root.iter("testcase"))
    if len(cases) != expected_count:
        raise ValueError(f"supplemental JUnit contains {len(cases)} cases; expected exactly {expected_count}")
    actual = [junit_nodeid(case) for case in cases]
    if len(set(actual)) != expected_count:
        raise ValueError("supplemental JUnit contains duplicate case identities")
    expected_set = set(expected)
    actual_set = set(actual)
    if actual_set != expected_set:
        raise ValueError(
            f"supplemental JUnit identities differ; missing={sorted(expected_set - actual_set)}, "
            f"extra={sorted(actual_set - expected_set)}"
        )
    for case in cases:
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error")):
            raise ValueError(f"supplemental PG case did not pass: {junit_nodeid(case)}")
    return {"case_count": len(cases), "nodeids": actual}


def add_provenance(report: Path, source_commit: str, manifest_sha256: str) -> None:
    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        raise ValueError("supplemental JUnit contains no testsuite")
    for suite in suites:
        properties = suite.find("properties")
        if properties is None:
            properties = ET.Element("properties")
            suite.insert(0, properties)
        ET.SubElement(properties, "property", name="source_commit", value=source_commit)
        ET.SubElement(properties, "property", name="required_cases_manifest_sha256", value=manifest_sha256)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(report, encoding="utf-8", xml_declaration=True)


def report_totals(reports: Path) -> dict[str, int]:
    totals = {"passed": 0, "failed": 0, "skipped": 0}
    for report in reports.glob("*.xml"):
        for case in ET.parse(report).getroot().iter("testcase"):
            key = "skipped" if case.find("skipped") is not None else (
                "failed" if any(case.find(tag) is not None for tag in ("failure", "error")) else "passed")
            totals[key] += 1
    return totals


def write_required_report(tree: ET.ElementTree, report: Path, groups: dict) -> None:
    required = ET.Element("testsuite")
    for case in tree.getroot().iter("testcase"):
        if case.get("classname", "").rsplit(".", 1)[-1] in groups:
            required.append(case)
    ET.ElementTree(required).write(report)


def write_supplement_report(tree: ET.ElementTree, report: Path, wanted: set[str]) -> None:
    selected = ET.Element("testsuite")
    for case in tree.getroot().iter("testcase"):
        node = junit_nodeid(case)
        if node in wanted:
            selected.append(case)
    ET.ElementTree(selected).write(report)

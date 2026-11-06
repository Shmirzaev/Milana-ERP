"""Run exactly the isolated Purchasing/Fabric PostgreSQL cases and validate JUnit evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


MANIFEST = Path(__file__).with_name("refactor_pg_required_cases.json")
EXPECTED_COUNT = 17
EXPECTED_ADMIN_DSN = "postgresql+psycopg2://postgres@127.0.0.1:55432/postgres"
EXPECTED_PREFIX = "review_ci_refactor_"


def expected_nodeids() -> list[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    nodeids = data.get("isolated_supplemental_cases")
    if not isinstance(nodeids, list) or len(nodeids) != EXPECTED_COUNT:
        raise ValueError("manifest must contain exactly 17 isolated supplemental node IDs")
    if any(not isinstance(nodeid, str) or "::" not in nodeid for nodeid in nodeids):
        raise ValueError("manifest contains an invalid supplemental node ID")
    if len(set(nodeids)) != EXPECTED_COUNT:
        raise ValueError("manifest contains duplicate supplemental node IDs")
    allowed = {
        "backend/app/tests/test_purchase_request_reject_postgres_followup.py": 7,
        "backend/app/tests/test_fabric_scan_postgres_followup.py": 10,
    }
    counts = {path: 0 for path in allowed}
    for nodeid in nodeids:
        path = nodeid.split("::", 1)[0]
        if path not in counts:
            raise ValueError(f"unapproved supplemental module in manifest: {path}")
        counts[path] += 1
    if counts != allowed:
        raise ValueError(f"supplemental module counts changed: {counts}")
    return nodeids


def require_ci_instance() -> None:
    if os.environ.get("MILANA_REQUIRE_TEST_PG") != "1":
        raise ValueError("supplemental PostgreSQL gate requires MILANA_REQUIRE_TEST_PG=1")
    raw = os.environ.get("MILANA_TEST_PG_INSTANCE")
    if not raw:
        raise ValueError("supplemental PostgreSQL gate requires MILANA_TEST_PG_INSTANCE")
    try:
        instance = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("MILANA_TEST_PG_INSTANCE is invalid JSON") from error
    if (not isinstance(instance, dict)
            or instance.get("host") != "127.0.0.1"
            or instance.get("port") != 55432
            or instance.get("admin_dsn") != EXPECTED_ADMIN_DSN
            or instance.get("target_prefix") != EXPECTED_PREFIX
            or not str(instance.get("server_version", "")).startswith("17.")
            or not str(instance.get("system_identifier", "")).isdecimal()
            or not str(instance.get("data_directory", "")).startswith("/")):
        raise ValueError("MILANA_TEST_PG_INSTANCE does not identify this job's approved PG17 target")


def junit_nodeid(case: ET.Element) -> str:
    module = case.get("classname", "").rsplit(".", 1)[-1]
    name = case.get("name", "")
    if not module or not name:
        raise ValueError("JUnit case is missing classname or name")
    return f"backend/app/tests/{module}.py::{name}"


def check_report(report: Path, expected: list[str]) -> dict[str, object]:
    root = ET.parse(report).getroot()
    cases = list(root.iter("testcase"))
    if len(cases) != EXPECTED_COUNT:
        raise ValueError(f"supplemental JUnit contains {len(cases)} cases; expected exactly {EXPECTED_COUNT}")
    actual = [junit_nodeid(case) for case in cases]
    if len(set(actual)) != EXPECTED_COUNT:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        require_ci_instance()
        expected = expected_nodeids()
        root = Path(__file__).resolve().parents[1]
        backend = root / "backend"
        report = args.report.resolve()
        if report.exists():
            raise ValueError("report path already exists; choose a fresh CI report path")
        if not report.parent.is_dir():
            raise ValueError("report parent directory must already exist")
        source_commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10
        ).strip()
        manifest_sha256 = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        selected = []
        for nodeid in expected:
            path, name = nodeid.split("::", 1)
            selected.append(str(root / path) + "::" + name)
        command = [
            sys.executable, "-m", "pytest", "--noconftest", "--runxfail",
            "-p", "no:cacheprovider", "-c", str(root / "pyproject.toml"),
            "--rootdir", str(root), "-q", *selected, f"--junitxml={report}",
        ]
        completed = subprocess.run(command, cwd=backend, check=False, timeout=1800)
        if not report.is_file():
            raise ValueError("supplemental pytest did not produce its JUnit report")
        add_provenance(report, source_commit, manifest_sha256)
        evidence = check_report(report, expected)
        if completed.returncode:
            raise ValueError(f"supplemental pytest exited with status {completed.returncode}")
        print(json.dumps({
            "required_pg_supplement": "PASS",
            "source_commit": source_commit,
            "required_cases_manifest_sha256": manifest_sha256,
            "case_count": evidence["case_count"],
        }, sort_keys=True))
        return 0
    except (OSError, subprocess.SubprocessError, ValueError, ET.ParseError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
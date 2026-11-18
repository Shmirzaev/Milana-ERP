"""Challenge the installed QA gate's completeness, source binding and refusal rules."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import auto_release_probe as probe
import auto_release_site_gate as gate
import auto_release_stage as staging
from test_auto_release import plan
from release_manifest import identity


class InstalledStageTests(unittest.TestCase):
    def setUp(self):
        # Exact stage() source from the separately hash-pinned live controller.
        source = (Path(__file__).parent / "fixtures/slotctl_stage_13a9e19.txt").read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),
                         "d2e3296f6b77899e297b8b28084b01ccac9d195778a21f14d727c4026a9af7b7")
        self.ctl = ModuleType("actual_installed_stage")
        exec(source, self.ctl.__dict__)
        self.ctl.BASE = Path("/opt/milana-erp")
        self.ctl.DB_POOL_SIZE, self.ctl.DB_MAX_OVERFLOW, self.ctl.BACKEND_WORKERS = 8, 4, 2
        self.ctl.container_name = lambda role, slot: f"milana-{role}-{slot}"
        self.ctl.slot_port = lambda role, slot: 18001
        self.ctl.json = json
        for name in ("validate_backend_connection_budget", "inspect_image", "remove_inactive_container",
                     "wait_for_health", "warm", "run"):
            setattr(self.ctl, name, Mock())
        self.original = self.ctl.run

    def test_actual_installed_stage_adds_only_release_environment_and_restores_runner(self):
        staging.stage(self.ctl, "backend", "blue", "20261117_120000", "immutable-image")
        self.assertIs(self.ctl.run, self.original)
        args = self.original.call_args.args
        self.assertEqual(args[-3:], ("-e", "RELEASE_ID=20261117_120000", "immutable-image"))
        self.assertEqual(args.count("-e"), 4)
        self.ctl.remove_inactive_container.assert_called_once_with("backend", "blue")

    def test_unexpected_pool_and_failure_do_not_forward_an_unreviewed_run(self):
        self.ctl.DB_POOL_SIZE = 9
        with self.assertRaises(ValueError):
            staging.stage(self.ctl, "backend", "blue", "20261117_120000", "immutable-image")
        self.original.assert_not_called()
        self.assertIs(self.ctl.run, self.original)
        self.ctl.DB_POOL_SIZE = 8
        self.original.side_effect = RuntimeError("controlled failure")
        with self.assertRaises(RuntimeError):
            staging.stage(self.ctl, "backend", "blue", "20261117_120000", "immutable-image")
        self.assertIs(self.ctl.run, self.original)


class RuntimeGateTests(unittest.TestCase):
    def test_real_docker_process_contract_and_stderr_errors_are_enforced(self):
        def processes(args, **kwargs):
            if "pid" not in args[-1].split(","):
                raise RuntimeError("Docker requires the PID column")
            return b"PID ARGS\n1 multiprocessing.spawn spawn_main\n2 multiprocessing.spawn spawn_main\n"
        logs = Mock(returncode=0, stdout=b"", stderr=b"")
        with patch.object(gate, "inspect", return_value={}), patch.object(gate, "assert_runtime"), \
                patch.object(gate, "command", side_effect=processes), \
                patch.object(gate.subprocess, "run", return_value=logs):
            gate.runtime_check({"Image": "image", "Id": "owned"}, backend=True)
            logs.stderr = b"Traceback: failed application operation"
            with self.assertRaisesRegex(ValueError, "error logs"):
                gate.runtime_check({"Image": "image", "Id": "owned"}, backend=True)


class CompleteFactsTests(unittest.TestCase):
    def read(self, payloads):
        with patch.object(probe, "get", side_effect=[(p, 1, 20) for p in payloads]):
            return probe.full_read("http://unused", "/read", True, "not-a-real-token")

    def test_all_pages_and_complete_ordered_fields_are_hashed(self):
        first = self.read([{"rows": [{"id": 1, "quantity": 9}], "total": 2},
                           {"rows": [{"id": 2, "quantity": 8}], "total": 2}])
        self.assertEqual(first["rows"], 2)
        for changed in ([{"id": 1, "quantity": 10}, {"id": 2, "quantity": 8}],
                        [{"id": 2, "quantity": 8}, {"id": 1, "quantity": 9}]):
            after = self.read([{"rows": changed, "total": 2}])
            self.assertNotEqual(first["ordered_facts_sha256"], after["ordered_facts_sha256"])

    def test_missing_total_repeat_truncation_and_moving_data_are_refused(self):
        invalid = [
            [{"rows": [], "total": None}],
            [{"rows": [1], "total": 3}, {"rows": [1], "total": 3}],
            [{"rows": [1], "total": 3}, {"rows": [], "total": 3}],
            [{"rows": [1], "total": 3}, {"rows": [2], "total": 4}],
            [{"rows": [1, 2], "total": 1}],
        ]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(probe.ProbeRefusal):
                self.read(data)

    def test_performance_budgets_are_not_weakened(self):
        self.assertEqual(probe.performance([100] * 21, [105] * 21)["samples_per_slot"], 21)
        for times in ([111] * 21, [100] * 19 + [116] * 2):
            with self.assertRaises(probe.ProbeRefusal):
                probe.performance([100] * 21, times)


class ApplicationApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.p = plan()
        self.changes = ["backend/app/changed.py"]
        self.approval = {"identity": identity(self.p), "changed_paths": self.changes,
                         "reviewed_by": "test-reviewer", "checked_at": time.time(), "evidence": {}}
        # Root ownership is a deployment-host invariant; temporary CI fixtures have
        # the runner's UID. Keep real file digests and path/symlink checks active.
        def fixture_trusted(path, expected=None):
            if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Evidence digest mismatch")
        self.trust = patch.object(gate, "trusted", side_effect=fixture_trusted)
        self.trust.start()
        self.addCleanup(self.trust.stop)
        for kind in gate.KINDS:
            artifact = {"identity": identity(self.p), "kind": kind,
                        "checks": [{"name": "observed_result", "expected": "actual-hash", "actual": "actual-hash"}]}
            if kind == "browser":
                image = self.root / "screenshot.png"
                image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"test-image")
                artifact.update(console_errors=0, screenshots=[self.reference(image)])
            path = self.root / (kind + ".json")
            path.write_text(json.dumps(artifact))
            self.approval["evidence"][kind] = self.reference(path)

    def reference(self, path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def invoke(self, approval=None):
        (self.root / (self.p["commit"] + ".json")).write_text(json.dumps(approval or self.approval))
        return gate.application_approval(self.p, self.changes, self.root)

    def test_exact_source_and_artifacts_are_required_for_application_changes(self):
        self.assertTrue(self.invoke()["application_changed"])
        for change in ({"identity": "another-plan"}, {"changed_paths": []},
                       {"checked_at": time.time() - 10801}, {"reviewed_by": ""}, {"evidence": {}}):
            altered = {**self.approval, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.invoke(altered)

    def test_no_approval_is_invented_for_deployment_only_changes(self):
        self.assertEqual(gate.application_approval(self.p, [], self.root), {"application_changed": False})
        self.assertEqual(gate.changed_application_paths({"deploy/a.py": "old"}, {"deploy/a.py": "new"}), [])
        self.assertEqual(gate.changed_application_paths({"backend/a.py": "old"}, {}), ["backend/a.py"])

    def test_artifact_tampering_failed_results_and_boolean_stubs_are_refused(self):
        path = self.root / "permissions.json"
        original = path.read_text()
        path.write_text(original + " ")
        with self.assertRaises(ValueError):
            self.invoke()
        for checks in ([{"name": "bad", "actual": 200, "expected": 403}],
                       [{"name": "stub", "actual": True, "expected": True}], []):
            artifact = json.loads(original)
            artifact["checks"] = checks
            path.write_text(json.dumps(artifact))
            self.approval["evidence"]["permissions"] = self.reference(path)
            with self.assertRaises(ValueError):
                self.invoke()

    def test_evidence_outside_protected_folder_is_refused(self):
        altered = copy.deepcopy(self.approval)
        altered["evidence"]["browser"]["path"] = str(self.root.parent / "outside.json")
        with self.assertRaises(ValueError):
            self.invoke(altered)


if __name__ == "__main__":
    unittest.main()

"""Offline checks for pytest partitioning and aggregate coverage evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from run_backend_regression_shard import collection_digest, node_digest, partition_nodes, verify_shards


RUNNER = Path(__file__).with_name("run_backend_regression_shard.py")


class PartitionTests(unittest.TestCase):
    def test_whole_modules_balance_deterministically_and_preserve_order(self):
        # Begin with a small module and interleave the IDs to test execution order.
        groups = {
            f"test_{name}.py": [f"test_{name}.py::test_case[{i}]" for i in range(size)]
            for name, size in [("f", 1), ("c", 4), ("a", 7), ("e", 2), ("d", 3), ("b", 6)]
        }
        ids = [group[i] for i in range(7) for group in groups.values() if len(group) > i]
        shards = partition_nodes(ids, 3)
        self.assertEqual([len(shard) for shard in shards], [8, 8, 7])
        self.assertCountEqual([nodeid for shard in shards for nodeid in shard], ids)
        self.assertEqual([set(shard) for shard in shards], [set(shard) for shard in partition_nodes(ids[::-1], 3)])
        for group in groups.values():
            self.assertEqual(sum(set(group) <= set(shard) for shard in shards), 1)
        for shard in shards:
            self.assertEqual(shard, [nodeid for nodeid in ids if nodeid in shard])

    def test_rejects_duplicate_ids_and_insufficient_modules(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            partition_nodes(["test_a.py::test_x"] * 2, 2)
        with self.assertRaisesRegex(ValueError, "Only 1"):
            partition_nodes(["test_a.py::test_x", "test_a.py::test_y"], 2)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.digests = [node_digest(f"test_{name}.py::test_example") for name in ("a", "b", "c")]
        self.manifests = [{
            "version": 1,
            "index": index,
            "count": 2,
            "collection_count": len(self.digests),
            "collection_sha256": collection_digest(self.digests),
            "results": [{"node_sha256": digest, "outcome": "passed"} for digest in digests],
        } for index, digests in enumerate((self.digests[:2], self.digests[2:]), start=1)]

    def write(self, slot):
        path = self.directory / f"backend-regression-{slot + 1}" / "backend-shard.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(self.manifests[slot]), encoding="utf-8")

    def verify(self):
        self.write(0)
        self.write(1)
        verify_shards(2, self.directory)

    def test_valid_complete_artifacts_accept_setup_skip(self):
        self.manifests[0]["results"][1]["outcome"] = "skipped"
        self.verify()

    def test_missing_manifest_rejects(self):
        self.write(0)
        with self.assertRaisesRegex(ValueError, "Expected 2 shard manifests, found 1"):
            verify_shards(2, self.directory)

    def test_duplicate_index_rejects(self):
        self.manifests[1]["index"] = 1
        with self.assertRaisesRegex(ValueError, "duplicate shard index"):
            self.verify()

    def test_duplicate_case_across_shards_rejects(self):
        self.manifests[1]["results"][0]["node_sha256"] = self.digests[0]
        with self.assertRaisesRegex(ValueError, "Duplicate test"):
            self.verify()

    def test_duplicate_case_within_a_shard_rejects(self):
        self.manifests[0]["results"][1]["node_sha256"] = self.digests[0]
        with self.assertRaisesRegex(ValueError, "Duplicate test"):
            self.verify()

    def test_incomplete_union_rejects(self):
        self.manifests[0]["results"].pop()
        with self.assertRaisesRegex(ValueError, "do not match the full pytest collection"):
            self.verify()

    def test_tamper_with_case_id_at_same_count_rejects(self):
        self.manifests[0]["results"][1]["node_sha256"] = node_digest("other.py::test_substituted")
        with self.assertRaisesRegex(ValueError, "do not match the full pytest collection"):
            self.verify()

    def test_mismatching_full_collections_reject(self):
        self.manifests[1]["collection_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "collected different pytest suites"):
            self.verify()

    def test_no_terminal_result_rejects(self):
        self.manifests[1]["results"][0]["outcome"] = "running"
        with self.assertRaisesRegex(ValueError, "Invalid result digest or outcome"):
            self.verify()


class PytestRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.backend = self.directory / "backend"
        self.tests = self.backend / "app" / "tests"
        self.tests.mkdir(parents=True)
        (self.backend / "pytest.ini").write_text("[pytest]\ntestpaths = app/tests\n", encoding="utf-8")
        (self.tests / "test_readiness_operation_characterization.py").write_text(
            "raise AssertionError('readiness suite belongs to a separate job')\n", encoding="utf-8",
        )

    def run_shard(self, index, count):
        manifest = self.directory / f"backend-regression-{index}" / "backend-shard.json"
        outcome = subprocess.run(
            [sys.executable, str(RUNNER), "run", "--index", str(index), "--count", str(count),
             "--manifest", str(manifest)],
            cwd=self.backend, capture_output=True, text=True, timeout=25,
        )
        return manifest, outcome

    def test_pytest_setup_skip_and_pass_are_recorded_without_parameter_ids(self):
        (self.tests / "test_a.py").write_text(
            "import pytest\n"
            "@pytest.fixture\n"
            "def skip_setup():\n"
            "    pytest.skip('fixture intentionally unavailable')\n"
            "@pytest.mark.parametrize('value', ['opaque-parameter-value'])\n"
            "def test_skip(skip_setup, value):\n"
            "    raise AssertionError('should be skipped before call')\n",
            encoding="utf-8",
        )
        (self.tests / "test_b.py").write_text("def test_pass():\n    assert True\n", encoding="utf-8")
        outcomes = []
        for index in (1, 2):
            manifest, completed = self.run_shard(index, 2)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            raw = manifest.read_text(encoding="utf-8")
            self.assertNotIn("opaque-parameter-value", raw)
            self.assertNotIn("test_skip", raw)
            outcome = json.loads(raw)["results"][0]["outcome"]
            outcomes.append(outcome)
        self.assertCountEqual(outcomes, ["passed", "skipped"])
        verify_shards(2, self.directory)

    def test_pytest_failure_removes_stale_manifest(self):
        (self.tests / "test_a.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
        stale = self.directory / "backend-regression-1" / "backend-shard.json"
        stale.parent.mkdir()
        stale.write_text("stale", encoding="utf-8")
        manifest, completed = self.run_shard(1, 1)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertFalse(manifest.exists())


if __name__ == "__main__":
    unittest.main()

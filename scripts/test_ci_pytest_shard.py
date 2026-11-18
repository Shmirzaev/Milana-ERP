"""Exercise partition coverage, module ownership and failing-shard exit status."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


class ShardTests(unittest.TestCase):
    def test_every_case_runs_once_and_failure_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for module, size in enumerate((7, 5, 3, 2, 1)):
                (root / f"test_group_{module}.py").write_text(
                    "\n".join(f"def test_case_{case}(): assert {module != 4}" for case in range(size))
                )
            seen = set()
            owners = {}
            failures = 0
            for shard in range(4):
                report = root / f"report-{shard}.xml"
                env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent),
                       "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "-p", "ci_pytest_shard",
                     f"--ci-shard={shard}", "--ci-shards=4", f"--junitxml={report}", str(root)],
                    cwd=root, env=env, capture_output=True, text=True,
                )
                self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
                failures += result.returncode
                for case in ET.parse(report).getroot().iter("testcase"):
                    identity = (case.attrib["classname"], case.attrib["name"])
                    self.assertNotIn(identity, seen)
                    seen.add(identity)
                    module = case.attrib["classname"]
                    self.assertEqual(owners.setdefault(module, shard), shard)
            self.assertEqual(len(seen), 18)
            self.assertEqual(failures, 1)


if __name__ == "__main__":
    unittest.main()

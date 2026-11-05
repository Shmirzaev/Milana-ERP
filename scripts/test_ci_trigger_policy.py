"""Focused contracts for duplicate-run prevention and protected release/QA events."""
import ast
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ("ci.yml", "refactor-operation-postgres.yml")
QA_BRANCHES = {
    "codex/ismail-finance-pilot-20261025",
    "codex/ismail-brand-feedback-20261028",
    "codex/ismail-combined-review-20261028",
}


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


class CITriggerPolicyTests(unittest.TestCase):
    def test_validation_pushes_are_only_integration_and_exact_qa_refs(self):
        self.assertEqual(set(workflow("ci.yml")["on"]["push"]["branches"]), {"main", "clone_main"} | QA_BRANCHES)

    def test_qa_push_exceptions_match_the_existing_artifact_authorization(self):
        tree = ast.parse((ROOT / "frontend/scripts/stage_qa_runtime.py").read_text())
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "EXPECTED_REFS" for target in node.targets))
        authorized = set(ast.literal_eval(assignment.value.args[0]))
        self.assertEqual(authorized, {f"refs/heads/{branch}" for branch in QA_BRANCHES})

    def test_pg_pushes_are_only_integration_branches(self):
        self.assertEqual(workflow("refactor-operation-postgres.yml")["on"]["push"]["branches"], ["main", "clone_main"])

    def test_both_workflows_retain_pr_and_manual_events(self):
        for name in WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertIn("pull_request", workflow(name)["on"])
                self.assertIn("workflow_dispatch", workflow(name)["on"])

    def test_concurrency_shares_only_workflow_pr_and_never_replaces_pending_pushes(self):
        expected = "${{ github.workflow }}-${{ github.event_name == 'pull_request' && format('pr-{0}', github.event.pull_request.number) || format('{0}-{1}', github.ref, github.run_id) }}"
        for name in WORKFLOWS:
            with self.subTest(workflow=name):
                policy = workflow(name)["concurrency"]
                self.assertEqual(policy["group"], expected)
                self.assertEqual(policy["cancel-in-progress"], "${{ github.event_name == 'pull_request' }}")

    def test_release_images_remain_manual_and_rollback_qa_keeps_its_separate_push(self):
        self.assertEqual(workflow("ci.yml")["jobs"]["release"]["if"], "github.event_name == 'workflow_dispatch'")
        rollback = workflow("rollback-image-qa.yml")
        self.assertEqual(rollback["on"]["push"]["branches"], ["codex/pack-customer-fg-rollback-20261103"])
        self.assertNotIn("concurrency", rollback)


if __name__ == "__main__":
    unittest.main()

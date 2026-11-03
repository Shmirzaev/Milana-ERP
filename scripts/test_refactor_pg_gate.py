"""Offline red/green checks for missing or skipped required PG evidence."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import run_refactor_pg_gate as gate


class RequiredPGGateTests(unittest.TestCase):
    def setUp(self):
        # Avoid changing global tmp settings; these tests never touch a database.
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def report(self):
        tree = ET.Element('testsuites')
        suite = ET.SubElement(tree, 'testsuite')
        for module, names in gate.REQUIRED_CASES.items():
            for name in names:
                ET.SubElement(suite, 'testcase', classname=f'app.tests.{module}', name=name)
        return tree

    def write_report(self, tree):
        path = self.root / 'report.xml'
        ET.ElementTree(tree).write(path)
        return path


    def test_catalog_create_groups_have_exact_registered_case_counts(self):
        for module, count in (("test_modelsize_create_postgres", 2), ("test_modelcolor_create_postgres", 27)):
            with self.subTest(module=module):
                self.assertIn(module, gate.REQUIRED_CASES)
                self.assertEqual(len(gate.REQUIRED_CASES[module]), count)
                self.assertEqual(len(set(gate.REQUIRED_CASES[module])), count)

    def test_catalog_create_missing_duplicate_and_nonpass_cannot_fill_gate(self):
        for module in ("test_modelsize_create_postgres", "test_modelcolor_create_postgres"):
            for mutation in ("missing", "duplicate", "failure", "error", "skipped"):
                with self.subTest(module=module, mutation=mutation):
                    self.assertIn(module, gate.REQUIRED_CASES)
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    rows = [row for row in suite if row.get("classname") == f"app.tests.{module}"]
                    if mutation == "missing":
                        suite.remove(rows[0])
                    elif mutation == "duplicate":
                        rows[-1].set("name", rows[0].get("name"))
                    else:
                        ET.SubElement(rows[0], mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_skipped_failed_and_error_evidence_are_rejected(self):
        for tag in ('skipped', 'failure', 'error'):
            with self.subTest(tag=tag):
                tree = self.report()
                ET.SubElement(next(tree.iter('testcase')), tag)
                with self.assertRaisesRegex(ValueError, 'did not pass'):
                    gate.check_report(self.write_report(tree))

    def test_missing_group_and_case_fail(self):
        tree = self.report()
        suite = next(tree.iter('testsuite'))
        suite.remove(next(tree.iter('testcase')))
        with self.assertRaisesRegex(ValueError, 'expected at least'):
            gate.check_report(self.write_report(tree))

    def test_missing_required_function_fails_even_with_same_total(self):
        tree = self.report()
        for case in tree.iter('testcase'):
            if case.get('name', '').startswith('test_pg_unknown_customer'):
                case.set('name', 'different_business_case')
        with self.assertRaisesRegex(ValueError, 'function missing'):
            gate.check_report(self.write_report(tree))

    def test_duplicate_cases_cannot_fill_count(self):
        tree = self.report()
        cases = list(tree.iter('testcase'))
        cases[1].attrib.update(cases[0].attrib)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            gate.check_report(self.write_report(tree))

    def test_unrelated_case_cannot_replace_any_required_case(self):
        for module in gate.REQUIRED_CASES:
            tree = self.report()
            selected = [case for case in tree.iter('testcase')
                        if case.get('classname') == f'app.tests.{module}']
            selected[0].set('name', 'unrelated_replacement_case')
            with self.subTest(module=module), self.assertRaises(ValueError):
                gate.check_report(self.write_report(tree))

    def test_one_rollback_parameter_cannot_replace_another(self):
        tree = self.report()
        for case in tree.iter('testcase'):
            if case.get('name') == 'test_pg_edit_and_audit_rollback_together_then_retry[audit_finalized]':
                case.set('name', 'test_pg_edit_and_audit_rollback_together_then_retry[unrelated]')
                break
        else:
            self.fail('frozen rollback parameter not present')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_additional_cases_are_allowed(self):
        tree = self.report()
        ET.SubElement(next(tree.iter('testsuite')), 'testcase',
                      classname='app.tests.test_bom_add_characterization', name='new_case')
        counts = gate.check_report(self.write_report(tree))
        self.assertEqual(counts['test_bom_add_characterization'], 55)

    def test_empty_and_malformed_evidence_fail(self):
        with self.assertRaisesRegex(ValueError, 'no test cases'):
            gate.check_report(self.write_report(ET.Element('testsuites')))
        path = self.root / 'malformed.xml'
        path.write_text('<testsuites>', encoding='utf-8')
        with self.assertRaises(ET.ParseError):
            gate.check_report(path)

    def test_required_config_is_checked_before_starting_pytest(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(gate.subprocess, 'run') as run:
            with patch('sys.argv', ['gate']), self.assertRaises(SystemExit) as error:
                gate.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_sanitization_removes_inherited_libpq_redirects_and_secrets(self):
        source = {"PGHOSTADDR": "10.0.0.1", "PGHOST": "other", "PGSERVICE": "remote",
                  "PGPASSWORD": "secret", "pgoptions": "-c search_path=public",
                  "MILANA_REQUIRE_TEST_PG": "1", "MILANA_TEST_PG_INSTANCE": "pinned", "PATH": "path"}
        clean = gate.sanitized_pg_environment(source, self.root)
        self.assertEqual({k for k in clean if k.upper().startswith("PG")}, {"PGPASSFILE", "PGSERVICEFILE"})
        self.assertEqual(clean["MILANA_TEST_PG_INSTANCE"], "pinned")
        self.assertEqual(clean["MILANA_REQUIRE_TEST_PG"], "1")
        self.assertEqual(Path(clean["PGPASSFILE"]).read_bytes(), b"")
        self.assertEqual(Path(clean["PGSERVICEFILE"]).read_bytes(), b"")

    def test_missing_brand_case_fails_even_if_other_group_has_extra(self):
        tree = self.report()
        suite = next(tree.iter('testsuite'))
        brand = next(case for case in tree.iter('testcase')
                     if case.get('classname') == 'app.tests.test_brand_create_postgres')
        suite.remove(brand)
        ET.SubElement(suite, 'testcase', classname='app.tests.test_bom_add_characterization', name='extra')
        with self.assertRaisesRegex(ValueError, 'expected at least'):
            gate.check_report(self.write_report(tree))

    def test_planning_rollback_boundary_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_planning_alternate_creation_postgres'
                    and case.get('name') ==
                    'test_pg_alternate_postflush_and_audit_failure_rollback_retry[log_action]')
        case.set('name', 'unrelated_replacement_case')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_customer_failure_point_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_customer_create_postgres'
                    and case.get('name') ==
                    'test_pg_route_failure_rolls_back_then_retry[audit_finalize]')
        case.set('name', 'test_pg_route_failure_rolls_back_then_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_brand_update_case_policy_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_brand_update_postgres'
                    and case.get('name') == 'test_pg_case_variant_update_is_allowed')
        case.set('name', 'unrelated_replacement_case')
        with self.assertRaises(ValueError):
            gate.check_report(self.write_report(tree))

    def test_supplier_commit_failure_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_supplier_create_postgres'
                    and case.get('name') == 'test_pg_route_failure_rolls_back_then_retry[commit]')
        case.set('name', 'test_pg_route_failure_rolls_back_then_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_customer_update_commit_case_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_customer_update_postgres'
                    and case.get('name') == 'test_pg_precommit_failure_rolls_back_and_retry[before_commit]')
        case.set('name', 'test_pg_precommit_failure_rolls_back_and_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_supplier_update_commit_case_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_supplier_update_postgres'
                    and case.get('name') == 'test_pg_precommit_failure_rolls_back_and_retry[before_commit]')
        case.set('name', 'test_pg_precommit_failure_rolls_back_and_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_customer_delete_commit_case_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_customer_delete_postgres'
                    and case.get('name') == 'test_pg_delete_precommit_failure_rolls_back_then_retry[before_commit]')
        case.set('name', 'test_pg_delete_precommit_failure_rolls_back_then_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_bootstrap_only_ci_and_fixed_endpoint(self):
        identity = self.root / 'identity.json'
        env = self.root / 'github-env'
        identity.write_text(json.dumps({'system_identifier': '123456', 'server_version': '17.11',
                                        'data_directory': '/var/lib/postgresql/data'}), encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'GitHub Actions'):
            gate.configure_ci(identity, env)
        self.assertFalse(env.exists())
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}, clear=True):
            gate.configure_ci(identity, env)
        values = dict(line.split('=', 1) for line in env.read_text().splitlines())
        config = json.loads(values['MILANA_TEST_PG_INSTANCE'])
        self.assertEqual(values['MILANA_REQUIRE_TEST_PG'], '1')
        self.assertEqual(config['host'], '127.0.0.1')
        self.assertEqual(config['port'], 55432)
        self.assertEqual(config['target_prefix'], 'review_ci_refactor_')

    def test_invalid_container_identity_fails_before_env_write(self):
        identity = self.root / 'identity.json'
        env = self.root / 'github-env'
        for changes in ({'system_identifier': 'invalid'}, {'server_version': '16.9'}, {'data_directory': 'relative'}):
            data = {'system_identifier': '123456', 'server_version': '17.11', 'data_directory': '/pgdata'}
            data.update(changes)
            identity.write_text(json.dumps(data), encoding='utf-8')
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}, clear=True), self.assertRaises(ValueError):
                gate.configure_ci(identity, env)
            self.assertFalse(env.exists())


    def test_approval_group_is_registered(self):
        module = 'test_purchase_request_approval_postgres'
        self.assertIn(module, gate.GROUPS)
        expected = [
            'test_approval_commits_actual_rows_audit_and_recipients[draft]',
            'test_approval_commits_actual_rows_audit_and_recipients[pending_approval]',
            'test_late_real_item_denial_rolls_back_flushed_participants_then_retry',
            'test_later_line_failure_rolls_back_first_line_then_retry',
            'test_public_approved_retry_ignores_invalid_lines_but_enforces_late_access',
            'test_empty_request_distinct_from_missing_lines',
            'test_fault_after_real_participant_rolls_back_and_retries[apply_purchase_request_line_approval]',
            'test_fault_after_real_participant_rolls_back_and_retries[apply_purchase_request_approval]',
            'test_fault_after_real_participant_rolls_back_and_retries[log_action]',
            'test_fault_after_real_participant_rolls_back_and_retries[notify_department]',
            'test_observed_row_lock_contention[approve]',
            'test_observed_row_lock_contention[reject]',
            'test_no_active_recipient_and_actor_exclusion',
            'test_full_audit_hash_chain',
            'test_invalid_payload_rolls_back_and_preserves_rows[missing]',
            'test_invalid_payload_rolls_back_and_preserves_rows[duplicate]',
            'test_invalid_payload_rolls_back_and_preserves_rows[wrong]',
            'test_invalid_payload_rolls_back_and_preserves_rows[blank_name]',
            'test_invalid_payload_rolls_back_and_preserves_rows[blank_photo]',
            'test_invalid_payload_rolls_back_and_preserves_rows[supplier_zero]',
            'test_invalid_payload_rolls_back_and_preserves_rows[supplier_absent]',
            'test_invalid_status_precedes_invalid_lines[rejected]',
            'test_invalid_status_precedes_invalid_lines[converted]',
            'test_missing_request_precedes_line_validation',
            'test_unknown_locked_status_stub_not_stored_pg_proof',
            'test_http_permission_denial_preserves_all_state',
            'test_audit_finalization_failure_rollback_and_retry',
        ]
        self.assertEqual(gate.REQUIRED_CASES[module], expected)
        self.assertEqual(gate.GROUPS[module], (len(expected), ()))

    def test_complete_evidence_passes(self):
        counts = gate.check_report(self.write_report(self.report()))
        self.assertEqual(sum(counts.values()), 219)

    def test_new_operation_groups_have_exact_required_identities(self):
        expected = {
            'test_item_update_operation_postgres': {
                'test_pg_update_fields_same_session_and_chain',
                'test_pg_update_audit_failure_rolls_back_then_retry[enqueue]',
                'test_pg_update_audit_failure_rolls_back_then_retry[finalize]',
                'test_pg_update_audit_failure_rolls_back_then_retry[commit]',
                'test_pg_two_conflicting_sku_updates_preserve_unique_index',
            },
            'test_modelsize_create_postgres': {
                'test_pg_create_atomic_audit_and_failure_retry',
                'test_pg_concurrent_duplicate_creates',
            },
        }
        for module, identities in expected.items():
            with self.subTest(module=module):
                self.assertIn(module, gate.GROUPS)
                self.assertEqual(set(gate.REQUIRED_CASES[module]), identities)
                self.assertEqual(gate.GROUPS[module][0], len(identities))

    def test_modelsize_delete_exact_required_identities(self):
        expected = {
            'test_delete_exact_id_and_audit',
            'test_delete_audit_failure_rolls_back_then_retry',
            'test_report_declared_incoming_fks',
            'test_pg_eco_and_wrong_scope_are_isolated',
            'test_pg_failure_rollback_retry[flush]',
            'test_pg_failure_rollback_retry[commit]',
            'test_pg_two_session_delete_observed_outcomes[True]',
            'test_pg_two_session_delete_observed_outcomes[False]',
            'test_pg_before_commit_audit_finalization_failure_rolls_back_and_retries',
            'test_pg_concurrent_http_post_delete_and_failure_partial_commit',
        }
        module = 'test_modelsize_delete_postgres'
        self.assertIn(module, gate.GROUPS)
        self.assertEqual(set(gate.REQUIRED_CASES[module]), expected)
        self.assertEqual(gate.GROUPS[module][0], len(expected))

    def test_new_operation_missing_or_unsuccessful_evidence_fails(self):
        modules = ('test_item_update_operation_postgres', 'test_modelsize_create_postgres',
                   'test_modelsize_delete_postgres', 'test_purchase_request_approval_postgres',
                   'test_modelcolor_create_postgres')
        for module in modules:
            for alteration in ('module', 'case', 'skipped', 'failure', 'error'):
                with self.subTest(module=module, alteration=alteration):
                    tree = self.report()
                    suite = next(tree.iter('testsuite'))
                    selected = [c for c in tree.iter('testcase')
                                if c.get('classname') == f'app.tests.{module}']
                    self.assertTrue(selected, f'missing registered module {module}')
                    if alteration == 'module':
                        for case in selected:
                            suite.remove(case)
                    elif alteration == 'case':
                        selected[0].set('name', 'unrelated_replacement_case')
                    else:
                        ET.SubElement(selected[0], alteration)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_duplicate_approval_identity_is_rejected(self):
        tree = self.report()
        cases = [c for c in tree.iter('testcase')
                 if c.get('classname') == 'app.tests.test_purchase_request_approval_postgres']
        cases[1].set('name', cases[0].get('name'))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            gate.check_report(self.write_report(tree))


if __name__ == '__main__':
    unittest.main()

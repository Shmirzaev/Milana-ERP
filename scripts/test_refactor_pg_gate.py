"""Offline red/green checks for missing or skipped required PG evidence."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import run_refactor_pg_gate as gate


def _unrelated_manifest_digest(manifest, excluded_module):
    frozen = {
        'description': manifest['description'],
        'collection_method': manifest['collection_method'],
        'sources': {key: value for key, value in manifest['sources'].items()
                    if key != excluded_module},
        'cases': {key: value for key, value in manifest['cases'].items()
                  if key != excluded_module},
        'isolated_supplemental_cases': manifest['isolated_supplemental_cases'],
    }
    return hashlib.sha256(json.dumps(
        frozen, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


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


    def test_support_required_cases_cannot_be_replaced_or_skipped(self):
        module = 'test_support_settings_postgres'
        expected = ('test_pg_section_merge_waits_on_exact_missing_or_existing_lock[company_info_missing]', 'test_pg_section_merge_waits_on_exact_missing_or_existing_lock[company_info_existing]', 'test_pg_section_merge_waits_on_exact_missing_or_existing_lock[financial_missing]', 'test_pg_section_merge_waits_on_exact_missing_or_existing_lock[financial_existing]', 'test_pg_section_merge_waits_on_exact_missing_or_existing_lock[preferences_missing]', 'test_pg_section_merge_waits_on_exact_missing_or_existing_lock[preferences_existing]', 'test_pg_logo_update_waits_on_shared_company_info_lock', 'test_pg_existing_row_wait_refreshes_after_preexisting_row_lock', 'test_pg_settings_failure_rolls_back_and_retry_persists_once[after_flush]', 'test_pg_settings_failure_rolls_back_and_retry_persists_once[after_audit]', 'test_pg_settings_failure_rolls_back_and_retry_persists_once[before_commit]', 'test_pg_typed_route_persists_wire_defaults_null_and_audit[company_info_wire]', 'test_pg_typed_route_persists_wire_defaults_null_and_audit[financial_wire]', 'test_pg_typed_route_persists_wire_defaults_null_and_audit[preferences_wire]', 'test_pg_typed_route_denials_invalid_and_unknown_have_no_writes', 'test_pg_typed_route_uses_schema_writer_session_and_one_commit')
        self.assertEqual(tuple(gate.REQUIRED_CASES[module]), expected)
        self.assertEqual(gate.GROUPS[module][0], 16)
        for name in expected:
            for invalid in ('replacement', 'skipped', 'failure', 'error'):
                with self.subTest(name=name, invalid=invalid):
                    tree = self.report()
                    case = next(c for c in tree.iter('testcase')
                                if c.get('classname') == f'app.tests.{module}'
                                and c.get('name') == name)
                    if invalid == 'replacement':
                        case.set('name', 'unrelated_support_case')
                    else:
                        ET.SubElement(case, invalid)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_support_source_pin_and_selected_functions_are_frozen(self):
        manifest = json.loads(Path(gate.__file__).with_name(
            'refactor_pg_required_cases.json').read_text(encoding='utf-8'))
        source = manifest['sources']['test_support_settings_postgres']
        self.assertEqual(source['revision'], 'c356294fc483cbcd28b9f18b6ba7b029c60d3d49')
        self.assertEqual(source['git_blob_sha256'], '70a512b0ef76028b40a1e25e96174feba8996b4f66b864131592bae8fd853be6')
        self.assertEqual(tuple(source['selected_functions']), ('test_pg_section_merge_waits_on_exact_missing_or_existing_lock', 'test_pg_logo_update_waits_on_shared_company_info_lock', 'test_pg_existing_row_wait_refreshes_after_preexisting_row_lock', 'test_pg_settings_failure_rolls_back_and_retry_persists_once', 'test_pg_typed_route_persists_wire_defaults_null_and_audit', 'test_pg_typed_route_denials_invalid_and_unknown_have_no_writes', 'test_pg_typed_route_uses_schema_writer_session_and_one_commit'))
        self.assertEqual(gate.GROUPS['test_support_settings_postgres'][1], ('test_pg_section_merge_waits_on_exact_missing_or_existing_lock', 'test_pg_logo_update_waits_on_shared_company_info_lock', 'test_pg_existing_row_wait_refreshes_after_preexisting_row_lock', 'test_pg_settings_failure_rolls_back_and_retry_persists_once', 'test_pg_typed_route_persists_wire_defaults_null_and_audit', 'test_pg_typed_route_denials_invalid_and_unknown_have_no_writes', 'test_pg_typed_route_uses_schema_writer_session_and_one_commit'))

    def test_complete_evidence_passes(self):
        counts = gate.check_report(self.write_report(self.report()))
        self.assertEqual(sum(counts.values()), 238)

    def test_sewing_output_source_pin_literal_cases_and_upstream_registry_are_frozen(self):
        module = 'test_sewing_output_postgres'
        functions = (
            'test_pg_factory_output_persists_all_participants_and_replays_once',
            'test_pg_band_output_uses_the_same_operation_and_preserves_retry_contract',
            'test_pg_sewing_output_refusals_have_no_persistent_effects',
            'test_pg_real_accessory_gate_refusal_rolls_back_flushed_block_then_retry',
            'test_pg_zero_defect_output_does_not_create_waste_or_advance_its_sequence',
            'test_pg_work_order_status_filter_uses_enum_and_wire_value',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds',
            'test_pg_sewing_output_waits_on_real_work_order_lock',
            'test_pg_band_output_waits_on_same_work_order_lock',
        )
        cases = (
            'test_pg_factory_output_persists_all_participants_and_replays_once',
            'test_pg_band_output_uses_the_same_operation_and_preserves_retry_contract',
            'test_pg_sewing_output_refusals_have_no_persistent_effects',
            'test_pg_real_accessory_gate_refusal_rolls_back_flushed_block_then_retry',
            'test_pg_zero_defect_output_does_not_create_waste_or_advance_its_sequence',
            'test_pg_work_order_status_filter_uses_enum_and_wire_value',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[record]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[accounting]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[actual_input]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[accessory_block]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[department]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[plans]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[workflow]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[waste]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[notification]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[audit]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[idempotency]',
            'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds[outer_commit_call]',
            'test_pg_sewing_output_waits_on_real_work_order_lock',
            'test_pg_band_output_waits_on_same_work_order_lock',
        )
        manifest = json.loads(Path(gate.__file__).with_name(
            'refactor_pg_required_cases.json').read_text(encoding='utf-8'))
        source = manifest['sources'][module]
        self.assertEqual(source['revision'], '81500dedb5cf89ef758d2547e949dc729dde9268')
        self.assertEqual(source['git_blob_sha256'],
                         'd06bff674777253cd431604f919a8500993c99c439888a754483a1c5a55ff991')
        self.assertEqual(tuple(source['selected_functions']), functions)
        self.assertEqual(tuple(manifest['cases'][module]), cases)
        self.assertEqual(gate.GROUPS[module], (20, functions))
        self.assertEqual(sum(len(items) for items in manifest['cases'].values()), 238)
        self.assertEqual(len(manifest['isolated_supplemental_cases']), 17)

        digest = _unrelated_manifest_digest(manifest, module)
        self.assertEqual(digest, 'c71bc5d2cf0e00281c2aa92d05a09bdb0a6559a5d2152d85e9e68b8b7ce0c0c9')

    def test_sewing_upstream_digest_works_without_git_history_or_checkout_cwd(self):
        module = 'test_sewing_output_postgres'
        manifest = json.loads(Path(gate.__file__).with_name(
            'refactor_pg_required_cases.json').read_text(encoding='utf-8'))
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as outside_checkout:
            try:
                os.chdir(outside_checkout)
                self.assertEqual(_unrelated_manifest_digest(manifest, module),
                                 'c71bc5d2cf0e00281c2aa92d05a09bdb0a6559a5d2152d85e9e68b8b7ce0c0c9')
            finally:
                os.chdir(original_cwd)

    def test_every_sewing_output_case_is_required_and_nonpasses_fail(self):
        module = 'test_sewing_output_postgres'
        for required_name in gate.REQUIRED_CASES[module]:
            for invalid in ('replacement', 'skipped', 'failure', 'error'):
                with self.subTest(case=required_name, invalid=invalid):
                    tree = self.report()
                    case = next(item for item in tree.iter('testcase')
                                if item.get('classname') == f'app.tests.{module}'
                                and item.get('name') == required_name)
                    if invalid == 'replacement':
                        case.set('name', 'unrelated_sewing_output_case')
                    else:
                        ET.SubElement(case, invalid)
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

    def test_each_new_refactor_pg_case_identity_is_required(self):
        new_modules = (
            'test_stock_batch_edit_postgres',
            'test_finance_payment_output_postgres',
            'test_collection_update_postgres',
            'test_price_calculation_purchasing_postgres',
            'test_package_print_run_postgres',
        )
        for module in new_modules:
            for required_name in gate.REQUIRED_CASES[module]:
                with self.subTest(module=module, case=required_name):
                    tree = self.report()
                    case = next(
                        item for item in tree.iter('testcase')
                        if item.get('classname') == f'app.tests.{module}'
                        and item.get('name') == required_name
                    )
                    case.set('name', 'unrelated_replacement_case')
                    with self.assertRaisesRegex(ValueError, 'function missing|case identities missing'):
                        gate.check_report(self.write_report(tree))

    def test_each_new_refactor_pg_group_is_required_even_when_total_is_preserved(self):
        new_modules = (
            'test_stock_batch_edit_postgres',
            'test_finance_payment_output_postgres',
            'test_collection_update_postgres',
            'test_price_calculation_purchasing_postgres',
            'test_package_print_run_postgres',
        )
        for module in new_modules:
            with self.subTest(module=module):
                tree = self.report()
                suite = next(tree.iter('testsuite'))
                selected = [
                    case for case in tree.iter('testcase')
                    if case.get('classname') == f'app.tests.{module}'
                ]
                for case in selected:
                    suite.remove(case)
                for index in range(len(selected)):
                    ET.SubElement(
                        suite,
                        'testcase',
                        classname='app.tests.test_bom_add_characterization',
                        name=f'extra_replacement_{module}_{index}',
                    )
                with self.assertRaisesRegex(ValueError, 'expected at least'):
                    gate.check_report(self.write_report(tree))

    def test_skip_in_new_refactor_pg_case_is_rejected(self):
        tree = self.report()
        case = next(
            item for item in tree.iter('testcase')
            if item.get('classname') == 'app.tests.test_stock_batch_edit_postgres'
            and item.get('name') ==
            'test_pg_batch_edit_refusals_leave_all_rows_and_audit_unchanged[reserved_warehouse]'
        )
        ET.SubElement(case, 'skipped')
        with self.assertRaisesRegex(ValueError, 'did not pass'):
            gate.check_report(self.write_report(tree))

    def test_each_purchase_receipt_case_identity_is_required(self):
        module = 'test_purchase_receipt_persistence_postgres'
        for name in gate.REQUIRED_CASES[module]:
            with self.subTest(case=name):
                tree = self.report()
                case = next(item for item in tree.iter('testcase')
                            if item.get('classname') == f'app.tests.{module}'
                            and item.get('name') == name)
                case.set('name', 'unrelated_replacement_case')
                with self.assertRaisesRegex(ValueError, 'function missing|case identities missing'):
                    gate.check_report(self.write_report(tree))

    def test_purchase_receipt_nonpasses_are_rejected(self):
        module = 'test_purchase_receipt_persistence_postgres'
        for name in gate.REQUIRED_CASES[module]:
            for tag in ('skipped', 'failure', 'error'):
                with self.subTest(case=name, tag=tag):
                    tree = self.report()
                    case = next(item for item in tree.iter('testcase')
                                if item.get('classname') == f'app.tests.{module}'
                                and item.get('name') == name)
                    ET.SubElement(case, tag)
                    with self.assertRaisesRegex(ValueError, 'did not pass'):
                        gate.check_report(self.write_report(tree))

    def test_each_manual_adjustment_pg_identity_is_required(self):
        module = 'test_payroll_adjustment_create_postgres'
        for name in gate.REQUIRED_CASES[module]:
            with self.subTest(case=name):
                tree = self.report()
                case = next(item for item in tree.iter('testcase')
                            if item.get('classname') == f'app.tests.{module}'
                            and item.get('name') == name)
                case.set('name', 'unrelated_replacement_case')
                with self.assertRaisesRegex(ValueError, 'function missing|case identities missing'):
                    gate.check_report(self.write_report(tree))

    def test_manual_adjustment_pg_nonpasses_are_rejected(self):
        module = 'test_payroll_adjustment_create_postgres'
        for name in gate.REQUIRED_CASES[module]:
            for tag in ('skipped', 'failure', 'error'):
                with self.subTest(case=name, tag=tag):
                    tree = self.report()
                    case = next(item for item in tree.iter('testcase')
                                if item.get('classname') == f'app.tests.{module}'
                                and item.get('name') == name)
                    ET.SubElement(case, tag)
                    with self.assertRaisesRegex(ValueError, 'did not pass'):
                        gate.check_report(self.write_report(tree))

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

    def test_shipment_reopen_source_pin_and_every_required_case_are_frozen(self):
        module = 'test_shipment_reopen_invoice_postgres'
        manifest = json.loads(
            (Path(gate.__file__).with_name('refactor_pg_required_cases.json'))
            .read_text(encoding='utf-8')
        )
        expected = (
            'test_pg_shipment_reopen_finance_participant_same_session_and_no_early_commit',
            'test_pg_shipment_reopen_preflights_every_invoice_before_any_finance_write',
            'test_pg_shipment_reopen_audit_failure_rolls_back_and_retry_commits_all',
            'test_pg_invoice_payment_and_shipment_reopen_serialize_on_invoice_row',
        )
        source = manifest['sources'][module]
        self.assertEqual(source['revision'], 'bb00ca3921404fe8482f774752ee0d05db45c180')
        self.assertEqual(
            source['git_blob_sha256'],
            'e03a4da9b9da696ede2f908fa9a5b1f6d95fdad17fd77c310167c2950cd24f97',
        )
        self.assertEqual(tuple(source['selected_functions']), expected)
        self.assertEqual(tuple(manifest['cases'][module]), expected)
        self.assertEqual(gate.GROUPS[module], (4, expected))

        tree = self.report()
        replacement = next(
            case for case in tree.iter('testcase')
            if case.get('classname') == f'app.tests.{module}'
        )
        replacement.set('name', 'unrelated_replacement_case')
        with self.assertRaisesRegex(ValueError, 'case identities missing|required PG function missing'):
            gate.check_report(self.write_report(tree))



if __name__ == '__main__':
    unittest.main()

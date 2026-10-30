"""Offline red/green checks for missing or skipped required PG evidence."""
import ast
import hashlib
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
        self.assertEqual(sum(counts.values()), 270)

    def test_task_create_source_pin_and_all_literal_case_identities_are_frozen(self):
        module = 'test_task_create_postgres'
        functions = (
            'test_pg_task_create_self_and_single_assignment_share_session_and_audit',
            'test_pg_task_broadcast_is_bounded_active_ordered_and_atomic',
            'test_pg_task_create_denials_leave_no_task_notification_or_audit',
            'test_pg_task_create_failure_after_flush_or_audit_commit_rolls_back_then_retry',
            'test_pg_repeated_identical_task_create_requests_remain_distinct',
            'test_pg_task_broadcast_refuses_when_authenticated_actor_becomes_inactive_before_recipient_select',
            'test_pg_concurrent_task_creates_keep_audit_chain',
        )
        cases = (
            'test_pg_task_create_self_and_single_assignment_share_session_and_audit',
            'test_pg_task_broadcast_is_bounded_active_ordered_and_atomic',
            'test_pg_task_create_denials_leave_no_task_notification_or_audit',
            'test_pg_task_create_failure_after_flush_or_audit_commit_rolls_back_then_retry[assigned-notification_after_flush]',
            'test_pg_task_create_failure_after_flush_or_audit_commit_rolls_back_then_retry[broadcast-notification_after_flush]',
            'test_pg_task_create_failure_after_flush_or_audit_commit_rolls_back_then_retry[self-audit_commit]',
            'test_pg_task_create_failure_after_flush_or_audit_commit_rolls_back_then_retry[assigned-audit_commit]',
            'test_pg_task_create_failure_after_flush_or_audit_commit_rolls_back_then_retry[broadcast-audit_commit]',
            'test_pg_repeated_identical_task_create_requests_remain_distinct',
            'test_pg_task_broadcast_refuses_when_authenticated_actor_becomes_inactive_before_recipient_select',
            'test_pg_concurrent_task_creates_keep_audit_chain',
        )
        manifest = json.loads(Path(gate.__file__).with_name(
            'refactor_pg_required_cases.json').read_text(encoding='utf-8'))
        source = manifest['sources'][module]
        self.assertEqual(source['revision'], '0567be4da6a86b5cdc494ba09dd5362c0914c0fc')
        self.assertEqual(source['git_blob_sha256'],
                         'd698d8f4f013ca9c7143ef4e45aad655e0a21dd67227e883aea4b39ac2ab12e8')
        self.assertEqual(tuple(source['selected_functions']), functions)
        self.assertEqual(tuple(manifest['cases'][module]), cases)
        self.assertEqual(gate.GROUPS[module], (11, functions))
        self.assertEqual(sum(len(items) for items in manifest['cases'].values()), 270)
        self.assertEqual(len(manifest['isolated_supplemental_cases']), 17)

    def test_task_update_source_pin_all_literal_cases_and_upstream_manifest_are_frozen(self):
        module = 'test_task_update_postgres'
        functions = (
            'test_pg_task_patch_reassignment_notification_audit_and_shared_session',
            'test_pg_task_patch_denials_preserve_task_notifications_and_audit',
            'test_pg_task_patch_preserves_omission_nullable_values_and_completion_time',
            'test_pg_task_patch_explicit_null_not_null_fields_keep_database_failure_semantics',
            'test_pg_task_patch_failure_rolls_back_then_retry',
            'test_pg_task_patch_concurrent_disjoint_fields_merge_with_two_audits',
            'test_pg_task_patch_repeat_has_no_idempotency_or_repeat_assignment_notice',
        )
        cases = (
            'test_pg_task_patch_reassignment_notification_audit_and_shared_session',
            'test_pg_task_patch_denials_preserve_task_notifications_and_audit[outsider-payload0-403-Not allowed]',
            'test_pg_task_patch_denials_preserve_task_notifications_and_audit[assignee-payload1-403-Assignees can only change status]',
            'test_pg_task_patch_denials_preserve_task_notifications_and_audit[creator-payload2-403-Only managers can assign tasks to other users]',
            'test_pg_task_patch_denials_preserve_task_notifications_and_audit[denied_manager-payload3-403-Only managers can assign tasks to other users]',
            'test_pg_task_patch_denials_preserve_task_notifications_and_audit[manager-payload4-404-Assigned user not found]',
            'test_pg_task_patch_preserves_omission_nullable_values_and_completion_time',
            'test_pg_task_patch_explicit_null_not_null_fields_keep_database_failure_semantics[title]',
            'test_pg_task_patch_explicit_null_not_null_fields_keep_database_failure_semantics[status]',
            'test_pg_task_patch_explicit_null_not_null_fields_keep_database_failure_semantics[priority]',
            'test_pg_task_patch_failure_rolls_back_then_retry[after_notification_flush]',
            'test_pg_task_patch_failure_rolls_back_then_retry[audit_finalize]',
            'test_pg_task_patch_failure_rolls_back_then_retry[before_commit_hook]',
            'test_pg_task_patch_concurrent_disjoint_fields_merge_with_two_audits',
            'test_pg_task_patch_repeat_has_no_idempotency_or_repeat_assignment_notice',
        )
        manifest = json.loads(
            Path(gate.__file__).with_name('refactor_pg_required_cases.json')
            .read_text(encoding='utf-8')
        )
        source = manifest['sources'][module]
        self.assertEqual(source['revision'], 'b194c7123546033dd1f881ebfdf9ce28f6a23e04')
        self.assertEqual(
            source['git_blob_sha256'],
            '37d85902e1bb0eae228ac8928eb9372816bde7f24c1f5e03e7912345d705234e',
        )
        self.assertEqual(tuple(source['selected_functions']), functions)
        self.assertEqual(tuple(manifest['cases'][module]), cases)
        self.assertEqual(gate.GROUPS[module], (15, functions))
        self.assertEqual(sum(len(items) for items in manifest['cases'].values()), 270)
        self.assertEqual(len(manifest['isolated_supplemental_cases']), 17)

        # Check upstream bytes semantically without consulting any Git history.
        upstream = json.loads(json.dumps(manifest))
        upstream['sources'].pop(module)
        upstream['cases'].pop(module)
        # Task COMPLETE was registered after the frozen Task UPDATE base.
        # Remove that additive module before checking the older upstream pin.
        upstream['sources'].pop('test_task_complete_postgres')
        upstream['cases'].pop('test_task_complete_postgres')
        upstream['sources'].pop('test_task_delete_postgres')
        upstream['cases'].pop('test_task_delete_postgres')
        canonical = json.dumps(upstream, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            '240356974f18b2a3b689d50a2466bb3836cbcc77b215570dea62e69a672f0800',
        )

    def test_each_task_update_case_is_required_and_nonpasses_fail(self):
        module = 'test_task_update_postgres'
        for required_name in gate.REQUIRED_CASES[module]:
            for invalid in ('replacement', 'missing', 'skipped', 'failure', 'error'):
                with self.subTest(case=required_name, invalid=invalid):
                    tree = self.report()
                    case = next(
                        item for item in tree.iter('testcase')
                        if item.get('classname') == f'app.tests.{module}'
                        and item.get('name') == required_name
                    )
                    if invalid == 'replacement':
                        case.set('name', 'unrelated_task_update_case')
                    elif invalid == 'missing':
                        next(tree.iter('testsuite')).remove(case)
                        ET.SubElement(
                            next(tree.iter('testsuite')),
                            'testcase',
                            classname='app.tests.test_bom_add_characterization',
                            name='missing_task_update_replacement',
                        )
                    else:
                        ET.SubElement(case, invalid)
                    with self.assertRaisesRegex(
                        ValueError,
                        'required PG group|required PG function missing|case identities missing|did not pass',
                    ):
                        gate.check_report(self.write_report(tree))

    def test_task_update_group_cannot_be_replaced_by_other_cases(self):
        module = 'test_task_update_postgres'
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
                name=f'task_update_replacement_{index}',
            )
        with self.assertRaisesRegex(ValueError, 'expected at least'):
            gate.check_report(self.write_report(tree))

    def test_task_complete_source_pin_cases_and_prior_registry_are_frozen(self):
        module = 'test_task_complete_postgres'
        functions = (
            'test_pg_task_complete_actor_notification_audit_and_shared_session',
            'test_pg_task_complete_does_not_notify_without_distinct_creator',
            'test_pg_task_complete_denials_preserve_all_task_effects',
            'test_pg_task_complete_missing_row_precedes_actor_authorization',
            'test_pg_task_complete_http_failure_rolls_back_then_fresh_request_retry',
            'test_pg_task_complete_same_session_rollback_clears_audit_state_then_retry',
            'test_pg_task_complete_repeat_resets_timestamp_and_duplicates_notice_and_audit',
            'test_pg_task_complete_concurrent_calls_remain_distinct_without_deduplication',
        )
        cases = (
            'test_pg_task_complete_actor_notification_audit_and_shared_session[assignee]',
            'test_pg_task_complete_actor_notification_audit_and_shared_session[manager]',
            'test_pg_task_complete_does_not_notify_without_distinct_creator[same_actor]',
            'test_pg_task_complete_does_not_notify_without_distinct_creator[missing_creator]',
            'test_pg_task_complete_denials_preserve_all_task_effects[outsider]',
            'test_pg_task_complete_denials_preserve_all_task_effects[denied_manager]',
            'test_pg_task_complete_missing_row_precedes_actor_authorization',
            'test_pg_task_complete_http_failure_rolls_back_then_fresh_request_retry[after_notification_flush]',
            'test_pg_task_complete_http_failure_rolls_back_then_fresh_request_retry[audit_finalize]',
            'test_pg_task_complete_http_failure_rolls_back_then_fresh_request_retry[before_commit_hook]',
            'test_pg_task_complete_same_session_rollback_clears_audit_state_then_retry[after_notification_flush]',
            'test_pg_task_complete_same_session_rollback_clears_audit_state_then_retry[audit_finalize]',
            'test_pg_task_complete_same_session_rollback_clears_audit_state_then_retry[before_commit_hook]',
            'test_pg_task_complete_repeat_resets_timestamp_and_duplicates_notice_and_audit',
            'test_pg_task_complete_concurrent_calls_remain_distinct_without_deduplication',
        )
        manifest = json.loads(
            (Path(gate.__file__).with_name('refactor_pg_required_cases.json'))
            .read_text(encoding='utf-8')
        )
        source = manifest['sources'][module]
        self.assertEqual(source['revision'], '865b8e1645970532bca47bfd638d03d81fc174bd')
        self.assertEqual(
            source['git_blob_sha256'],
            '27483adb76a148d9456f73c2505f6637e70b291e8e1c6f84a82fc3819967ab5f',
        )
        self.assertEqual(tuple(source['selected_functions']), functions)
        self.assertEqual(tuple(manifest['cases'][module]), cases)
        self.assertEqual(gate.GROUPS[module], (15, functions))
        self.assertEqual(sum(len(items) for items in manifest['cases'].values()), 270)
        self.assertEqual(len(manifest['isolated_supplemental_cases']), 17)

        # Prove every prior registry identity and pin remains unchanged without
        # consulting Git history (important in shallow CI checkouts).
        prior = json.loads(json.dumps(manifest))
        prior['sources'].pop(module)
        prior['cases'].pop(module)
        prior['sources'].pop('test_task_delete_postgres')
        prior['cases'].pop('test_task_delete_postgres')
        canonical = json.dumps(prior, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            'f1680c052f4f324a7c7cafb71506b2ff5d6a4471c2dbf3e13e5bdb6da1ff97b2',
        )

    def test_each_task_complete_case_is_required_and_nonpasses_fail(self):
        module = 'test_task_complete_postgres'
        for required_name in gate.REQUIRED_CASES[module]:
            for invalid in ('replacement', 'missing', 'skipped', 'failure', 'error'):
                with self.subTest(case=required_name, invalid=invalid):
                    tree = self.report()
                    suite = next(tree.iter('testsuite'))
                    case = next(
                        item for item in tree.iter('testcase')
                        if item.get('classname') == f'app.tests.{module}'
                        and item.get('name') == required_name
                    )
                    if invalid == 'replacement':
                        case.set('name', 'unrelated_task_complete_case')
                    elif invalid == 'missing':
                        suite.remove(case)
                        ET.SubElement(
                            suite,
                            'testcase',
                            classname='app.tests.test_bom_add_characterization',
                            name='missing_task_complete_replacement',
                        )
                    else:
                        ET.SubElement(case, invalid)
                    with self.assertRaisesRegex(
                        ValueError,
                        'required PG group|required PG function missing|case identities missing|did not pass',
                    ):
                        gate.check_report(self.write_report(tree))

    def test_task_complete_group_cannot_be_replaced_by_other_cases(self):
        module = 'test_task_complete_postgres'
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
                name=f'task_complete_replacement_{index}',
            )
        with self.assertRaisesRegex(ValueError, 'expected at least'):
            gate.check_report(self.write_report(tree))

    def test_task_delete_source_pin_ast_cases_and_prior_registry_are_frozen(self):
        module = 'test_task_delete_postgres'
        functions = (
            'test_pg_task_delete_creator_and_manager_share_session_audit_and_keep_notice',
            'test_pg_task_delete_denials_preserve_task_notice_audit_and_commit_state',
            'test_pg_task_delete_missing_row_precedes_authorization_without_writes',
            'test_pg_task_delete_failure_rolls_back_and_retries_on_same_session',
            'test_pg_task_delete_two_authorized_sessions_keep_current_duplicate_request_semantics',
        )
        cases = (
            'test_pg_task_delete_creator_and_manager_share_session_audit_and_keep_notice[creator-pending]',
            'test_pg_task_delete_creator_and_manager_share_session_audit_and_keep_notice[creator_with_manager_denied-completed]',
            'test_pg_task_delete_creator_and_manager_share_session_audit_and_keep_notice[manager-cancelled]',
            'test_pg_task_delete_denials_preserve_task_notice_audit_and_commit_state[assignee]',
            'test_pg_task_delete_denials_preserve_task_notice_audit_and_commit_state[outsider]',
            'test_pg_task_delete_denials_preserve_task_notice_audit_and_commit_state[denied_manager]',
            'test_pg_task_delete_missing_row_precedes_authorization_without_writes',
            'test_pg_task_delete_failure_rolls_back_and_retries_on_same_session[after_delete_flush]',
            'test_pg_task_delete_failure_rolls_back_and_retries_on_same_session[audit_finalize]',
            'test_pg_task_delete_failure_rolls_back_and_retries_on_same_session[before_commit_hook]',
            'test_pg_task_delete_two_authorized_sessions_keep_current_duplicate_request_semantics',
        )
        manifest = json.loads(Path(gate.__file__).with_name(
            'refactor_pg_required_cases.json').read_text(encoding='utf-8'))
        source = manifest['sources'][module]
        self.assertEqual(source['revision'], 'e677dad1545982c28513a3bacf5532e7fa9e1528')
        self.assertEqual(
            source['git_blob_sha256'],
            '1d0fcdbd22a0dc7a3e5608ca19a67b96bfb48da6e7303963768955e5bbcdaf1d',
        )
        self.assertEqual(tuple(source['selected_functions']), functions)
        self.assertEqual(tuple(manifest['cases'][module]), cases)
        self.assertEqual(gate.GROUPS[module], (11, functions))
        self.assertEqual(sum(len(items) for items in manifest['cases'].values()), 270)
        self.assertEqual(len(manifest['isolated_supplemental_cases']), 17)

        source_path = Path(gate.__file__).resolve().parents[1] / 'backend/app/tests/test_task_delete_postgres.py'
        source_bytes = source_path.read_bytes()
        self.assertEqual(hashlib.sha256(source_bytes).hexdigest(), source['git_blob_sha256'])
        syntax = ast.parse(source_bytes, filename=str(source_path))
        definitions = {
            node.name: node for node in syntax.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        ordered_functions = tuple(
            node.name for node in syntax.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions
        )
        self.assertEqual(ordered_functions, functions)

        derived_cases = []
        for name in functions:
            node = definitions[name]
            parameter_sets = None
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == 'parametrize'):
                    parameter_sets = (
                        ast.literal_eval(decorator.args[0]),
                        ast.literal_eval(decorator.args[1]),
                    )
                    break
            if parameter_sets is None:
                derived_cases.append(name)
                continue
            argnames, values = parameter_sets
            names = [part.strip() for part in argnames.split(',')] if isinstance(argnames, str) else list(argnames)
            for value in values:
                parts = [value] if len(names) == 1 else list(value)
                self.assertEqual(len(parts), len(names))
                derived_cases.append(f"{name}[{'-'.join(str(part) for part in parts)}]")
        self.assertEqual(tuple(derived_cases), cases)

        # Hash the current canonical manifest with only this additive registration
        # removed. This does not depend on Git history and protects every older
        # source pin, case identity, and supplemental identity.
        prior = json.loads(json.dumps(manifest))
        prior['sources'].pop(module)
        prior['cases'].pop(module)
        canonical = json.dumps(prior, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            '51c361b5f9ce43a13d1a3361965f6dcf2ca33fc57b825a0a3215f361bf1be63a',
        )

    def test_each_task_delete_case_is_required_and_nonpasses_fail(self):
        module = 'test_task_delete_postgres'
        for required_name in gate.REQUIRED_CASES[module]:
            for invalid in ('replacement', 'missing', 'skipped', 'failure', 'error'):
                with self.subTest(case=required_name, invalid=invalid):
                    tree = self.report()
                    suite = next(tree.iter('testsuite'))
                    case = next(
                        item for item in tree.iter('testcase')
                        if item.get('classname') == f'app.tests.{module}'
                        and item.get('name') == required_name
                    )
                    if invalid == 'replacement':
                        case.set('name', 'unrelated_task_delete_case')
                    elif invalid == 'missing':
                        suite.remove(case)
                        ET.SubElement(
                            suite,
                            'testcase',
                            classname=f'app.tests.{module}',
                            name='unrelated_task_delete_case',
                        )
                    else:
                        ET.SubElement(case, invalid)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_task_delete_duplicate_case_identity_and_group_replacement_fail(self):
        module = 'test_task_delete_postgres'
        tree = self.report()
        suite = next(tree.iter('testsuite'))
        first = next(
            item for item in tree.iter('testcase')
            if item.get('classname') == f'app.tests.{module}'
        )
        ET.SubElement(suite, 'testcase', attrib=dict(first.attrib))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            gate.check_report(self.write_report(tree))

        tree = self.report()
        suite = next(tree.iter('testsuite'))
        selected = [
            item for item in tree.iter('testcase')
            if item.get('classname') == f'app.tests.{module}'
        ]
        for case in selected:
            suite.remove(case)
        for index in range(len(selected)):
            ET.SubElement(
                suite,
                'testcase',
                classname='app.tests.test_bom_add_characterization',
                name=f'task_delete_replacement_{index}',
            )
        with self.assertRaisesRegex(ValueError, 'expected at least'):
            gate.check_report(self.write_report(tree))

    def test_each_task_create_case_is_required_and_nonpasses_fail(self):
        module = 'test_task_create_postgres'
        for required_name in gate.REQUIRED_CASES[module]:
            for invalid in ('replacement', 'skipped', 'failure', 'error'):
                with self.subTest(case=required_name, invalid=invalid):
                    tree = self.report()
                    case = next(item for item in tree.iter('testcase')
                                if item.get('classname') == f'app.tests.{module}'
                                and item.get('name') == required_name)
                    if invalid == 'replacement':
                        case.set('name', 'unrelated_task_create_case')
                    else:
                        ET.SubElement(case, invalid)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_task_create_group_cannot_be_replaced_by_unrelated_primary_cases(self):
        module = 'test_task_create_postgres'
        tree = self.report()
        suite = next(tree.iter('testsuite'))
        selected = [case for case in tree.iter('testcase')
                    if case.get('classname') == f'app.tests.{module}']
        for case in selected:
            suite.remove(case)
        for index in range(len(selected)):
            ET.SubElement(suite, 'testcase', classname='app.tests.test_bom_add_characterization',
                          name=f'task_replacement_{index}')
        with self.assertRaisesRegex(ValueError, 'expected at least'):
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

"""Offline red/green checks for missing or skipped required PG evidence."""
import json
import hashlib
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
        self.assertEqual(sum(counts.values()), 257)

    def test_model_image_upload_source_and_all_case_nodes_are_frozen(self):
        module = 'test_model_image_upload_postgres'
        functions = (
            'test_upload_image_type_preserves_null_and_normalization_contract',
            'test_upload_image_type_rejects_values_outside_the_action_subset',
            'test_upload_form_openapi_exposes_enum_contract_for_both_catalog_scopes',
            'test_pg_upload_form_rejects_unknown_enum_before_storage_or_rows',
            'test_pg_upload_persists_typed_image_through_worker_session_and_audits_once',
            'test_pg_upload_route_permission_denial_writes_nothing',
            'test_pg_upload_pattern_type_keeps_nonprimary_contract',
            'test_pg_upload_null_type_preserves_existing_primary',
            'test_pg_document_upload_persists_one_managed_file_without_thumbnails',
            'test_pg_document_upload_precommit_audit_failure_rolls_back_row_and_file',
            'test_pg_document_upload_partial_write_failure_leaves_no_file_or_row',
            'test_pg_cancel_after_worker_commit_keeps_file_and_row',
            'test_pg_cancel_during_image_processing_cleans_files_before_database_write',
            'test_pg_upload_scope_is_rechecked_in_worker_before_mapped_insert',
        )
        cases = (
            'test_upload_image_type_preserves_null_and_normalization_contract[None-None]',
            'test_upload_image_type_preserves_null_and_normalization_contract[   -None]',
            'test_upload_image_type_preserves_null_and_normalization_contract[ MODEL -model]',
            'test_upload_image_type_preserves_null_and_normalization_contract[Material-material]',
            'test_upload_image_type_preserves_null_and_normalization_contract[pattern-pattern]',
            'test_upload_image_type_rejects_values_outside_the_action_subset',
            'test_upload_form_openapi_exposes_enum_contract_for_both_catalog_scopes',
            'test_pg_upload_form_rejects_unknown_enum_before_storage_or_rows[standard-MIL]',
            'test_pg_upload_form_rejects_unknown_enum_before_storage_or_rows[usluga-ECO]',
            'test_pg_upload_persists_typed_image_through_worker_session_and_audits_once[standard-MIL]',
            'test_pg_upload_persists_typed_image_through_worker_session_and_audits_once[usluga-ECO]',
            'test_pg_upload_route_permission_denial_writes_nothing[standard]',
            'test_pg_upload_route_permission_denial_writes_nothing[usluga]',
            'test_pg_upload_pattern_type_keeps_nonprimary_contract',
            'test_pg_upload_null_type_preserves_existing_primary[None]',
            'test_pg_upload_null_type_preserves_existing_primary[   ]',
            'test_pg_document_upload_persists_one_managed_file_without_thumbnails[standard-MIL]',
            'test_pg_document_upload_persists_one_managed_file_without_thumbnails[usluga-ECO]',
            'test_pg_document_upload_precommit_audit_failure_rolls_back_row_and_file',
            'test_pg_document_upload_partial_write_failure_leaves_no_file_or_row',
            'test_pg_cancel_after_worker_commit_keeps_file_and_row',
            'test_pg_cancel_during_image_processing_cleans_files_before_database_write',
            'test_pg_upload_scope_is_rechecked_in_worker_before_mapped_insert',
        )
        manifest = json.loads(Path(gate.__file__).with_name(
            'refactor_pg_required_cases.json').read_text(encoding='utf-8'))
        source = manifest['sources'][module]
        self.assertEqual(source['revision'], '7290b56545c2c6257d6eb9ce9f0a1376e1c7f8e2')
        self.assertEqual(source['git_blob_oid'], 'f21801e3d5e379fa8bec77936aa09c213de8f530')
        self.assertEqual(source['git_blob_sha256'],
                         '8f490043b172294636d7070d3baa326ae948b13c7332d5f78c655c99bafe62c0')
        self.assertEqual(tuple(source['selected_functions']), functions)
        self.assertEqual(tuple(manifest['cases'][module]), cases)
        self.assertEqual(gate.GROUPS[module], (23, functions))
        self.assertEqual(sum(len(items) for items in manifest['cases'].values()), 257)
        self.assertEqual(len(manifest['isolated_supplemental_cases']), 17)

        baseline = dict(manifest)
        baseline['sources'] = {name: value for name, value in manifest['sources'].items() if name != module}
        baseline['cases'] = {name: value for name, value in manifest['cases'].items() if name != module}
        baseline_hash = hashlib.sha256(
            json.dumps(baseline, sort_keys=True, separators=(',', ':')).encode()
        ).hexdigest()
        self.assertEqual(baseline_hash, 'fd77edae0055c6c345a2da20f0282719dd565357ab15e84f6fd4ca2d297d44b8')
        # Restoring only the previous Image source identity reconstructs the
        # old cross-module canonical digests; it proves no other registry
        # content changed during the source refresh.
        historical = json.loads(json.dumps(manifest))
        historical['sources'][module].update(
            revision='35dad5f0fea1a013584da263e1dbc5e76fc0f7f1',
            git_blob_oid='01944edceced564efb7fd829f202c06f8ff3b607',
            git_blob_sha256='97f0633077c4907b5fd3197447ecca40554750e2c1e29f84647ce4d020c236d7',
        )
        old_bom_baseline = dict(historical)
        old_bom_baseline['sources'] = {
            name: value for name, value in historical['sources'].items()
            if name != 'test_bom_add_characterization'
        }
        old_bom_baseline['cases'] = {
            name: value for name, value in historical['cases'].items()
            if name != 'test_bom_add_characterization'
        }
        old_bom_baseline['approved_case_transitions'] = [
            item for item in historical['approved_case_transitions']
            if item.get('module') != 'test_bom_add_characterization'
        ]
        self.assertEqual(hashlib.sha256(
            json.dumps(old_bom_baseline, sort_keys=True, separators=(',', ':')).encode()
        ).hexdigest(), 'b8fca3b944e292a64120cf91e72ad2460624d4a8bb71a8427f5680824cd4e2a3')
        old_model_baseline = {
            'description': historical['description'],
            'collection_method': historical['collection_method'],
            'sources': {key: value for key, value in historical['sources'].items()
                        if key != 'test_model_paid_operations_postgres'},
            'cases': {key: value for key, value in historical['cases'].items()
                      if key != 'test_model_paid_operations_postgres'},
            'isolated_supplemental_cases': historical['isolated_supplemental_cases'],
        }
        self.assertEqual(hashlib.sha256(
            json.dumps(old_model_baseline, sort_keys=True, separators=(',', ':')).encode()
        ).hexdigest(), '93610adfe0a6bdc2a7cc59080070a0b3112d94f2f4f570f07cbe179f0e1b4f90')
        gate.verify_model_image_upload_source()

    def test_bom_source_refresh_retains_all_old_cases_and_requires_retry_case(self):
        module = 'test_bom_add_characterization'
        new_case = 'test_patch_late_audit_failure_rolls_back_and_same_session_retry'
        manifest = json.loads(Path(gate.__file__).with_name(
            'refactor_pg_required_cases.json').read_text(encoding='utf-8'))
        source = manifest['sources'][module]
        expected_functions = (
            'test_manual_normalizes_role_name_and_discards_stale_references',
            'test_manual_invalid_role_is_currently_service400_and_no_write',
            'test_inventory_link_ignores_supplied_role_and_whitespace_name',
            'test_inventory_role_length_still_validated_before_normalization',
            'test_standard_fabric_discards_nonexistent_batch_and_fills_blank_unit',
            'test_usluga_disallows_inventory_fabric_and_nonaccessory_categories',
            'test_batch_link_defaults_and_explicit_overrides',
            'test_reference_and_photo_failures_do_not_write',
            'test_batch_must_belong_to_selected_item',
            'test_wrong_catalog_scope_is404',
            'test_permission_revocation_is_enforced',
            'test_usluga_requires_selected_eco_factory',
            'test_existing_numeric_policy_and_pg_rounding_preserved',
            'test_second_main409_secondary_repeated_and_other_model_main_allowed',
            'test_patch_uses_canonical_roles_and_output_keeps_legacy_projection',
            new_case,
            'test_clone_and_variant_copy_roles_without_calling_add_bom',
            'test_same_session_audit_outer_commit_and_precommit_invisibility',
            'test_real_audit_failure_rolls_back_bom_and_audit',
            'test_actual_migration_checks_reject_invalid_storage',
            'test_nullable_sql_check_is_not_a_nonnull_role_guarantee',
            'test_competing_main_creates_reach_unique_index_one_business_outcome',
            'test_post_openapi_nullable_canonical_role_and_id_only_wire',
            'test_blanket_strict_role_mutation_would_break_inventory_compatibility',
        )
        self.assertEqual(source['revision'], '52102d4764544e0906f24630f434377b7e7ac259')
        self.assertEqual(source['git_blob_oid'], '812d64c8baf12c812b83f8d8f8968bace1fba442')
        self.assertEqual(source['git_blob_sha256'],
                         'eb92b3c28e49b7e77f94452bdaed5e2b008a59716d0052d0b38220a21cecc150')
        self.assertEqual(tuple(source['selected_functions']), expected_functions)
        self.assertEqual(gate.GROUPS[module], (55, ()))
        self.assertEqual(tuple(gate.REQUIRED_CASES[module]), tuple(manifest['cases'][module]))
        self.assertEqual(manifest['cases'][module].count(new_case), 1)
        prior_case_ids = [name for name in manifest['cases'][module] if name != new_case]
        self.assertEqual(len(prior_case_ids), 54)
        self.assertEqual(hashlib.sha256(
            json.dumps(prior_case_ids, separators=(',', ':')).encode()).hexdigest(),
            '0240903765081c312548d4c8bacb44ef4c92dc61d6996ca3712b3346ecab7943')
        prior_functions = [name for name in source['selected_functions'] if name != new_case]
        self.assertEqual(hashlib.sha256(
            json.dumps(prior_functions, separators=(',', ':')).encode()).hexdigest(),
            'ba559af056cff240178660c61828318f15ea5cb37ba61fcd06fcdecac031ccdd')

        transition = next(item for item in manifest['approved_case_transitions']
                          if item.get('module') == module)
        self.assertEqual(transition['transition_kind'], 'SOURCE_REFRESH')
        self.assertEqual(transition['previous_revision'],
                         '1e9d983e2b856cb66aaa32ea61c05505651996af')
        self.assertEqual(transition['previous_declared_content_sha256'],
                         '457f7831ed3b468bd59b291f3e9042e51a8ef73ce7b86ea3e90d7c474567fb4c')
        self.assertEqual(transition['previous_content_provenance'], {
            'audit_file': 'PG_REQUIRED_SOURCE_PROVENANCE_AUDIT_20261030.md',
            'audit_sha256': 'c1120ca6701324cda9c93a820a320ce2ee407e1bad515fd49b26c986ed2670b0',
            'verified_content_commit': '5b76a7108a33ec57cceacfd8c780cdde0a45f687',
            'verified_git_blob_oid': 'fca5e5ea536b09ce6aab5399c956abdd2ed58a8d',
            'meaning': ('The prior manifest hash is a historical content SHA-256; its revision label does not '
                        'resolve in this checkout. The provenance audit verified the hash against this '
                        'reachable historical Git blob.'),
        })
        self.assertEqual(transition['new_revision'], source['revision'])
        self.assertEqual(transition['new_git_blob_oid'], source['git_blob_oid'])
        self.assertEqual(transition['new_git_blob_sha256'], source['git_blob_sha256'])
        self.assertEqual(transition['approved_reviews'], [
            {
                'file': 'CAT_BOM_UPDATE_SOURCE_INDEPENDENT_REVIEW_20261030.md',
                'sha256': '3a81045fa82efdbae3f0df91546977728c547950a187aeabc272d100b96eb732',
            },
            {
                'file': 'CAT_BOM_UPDATE_SOURCE_DELTA_REVIEW_20261030.md',
                'sha256': 'b82298b6e6edc08c184cf9a908e0e12253932ba9ddea6c58a96e88e63c7395c8',
            },
        ])
        self.assertEqual(transition['retained_prior_module_case_count'], 54)
        self.assertEqual(transition['added_required_cases'], [new_case])
        self.assertEqual(transition['removed_required_cases'], [])
        self.assertEqual(transition['historical_runtime_receipts_reused'], [])
        gate.verify_bom_update_source()

        # Removing only this reviewed module's new source/case/transition delta
        # must reproduce the pre-refresh unrelated registry exactly.
        baseline = dict(manifest)
        baseline['sources'] = {name: value for name, value in manifest['sources'].items()
                               if name != module}
        baseline['cases'] = {name: value for name, value in manifest['cases'].items()
                             if name != module}
        baseline['approved_case_transitions'] = [
            item for item in manifest['approved_case_transitions']
            if item.get('module') != module
        ]
        self.assertEqual(hashlib.sha256(
            json.dumps(baseline, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'bd3fca3b95320acf08722aa940d1b5a9406100e4cb8ca0da37935fc6d2173399')
        self.assertEqual(sum(len(items) for items in manifest['cases'].values()), 257)
        self.assertEqual(sum(len(items) for items in manifest['cases'].values())
                         + len(manifest['isolated_supplemental_cases']), 274)

        for invalid in ('missing', 'replacement', 'skipped', 'failure', 'error'):
            tree = self.report()
            suite = next(tree.iter('testsuite'))
            case = next(item for item in tree.iter('testcase')
                        if item.get('classname') == f'app.tests.{module}'
                        and item.get('name') == new_case)
            if invalid == 'missing':
                suite.remove(case)
            elif invalid == 'replacement':
                case.set('name', 'unrelated_bom_case')
            else:
                ET.SubElement(case, invalid)
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                gate.check_report(self.write_report(tree))

    def test_each_model_image_upload_identity_cannot_be_missing_replaced_or_nonpassing(self):
        module = 'test_model_image_upload_postgres'
        for required_name in gate.REQUIRED_CASES[module]:
            for invalid in ('missing', 'replacement', 'skipped', 'failure', 'error'):
                with self.subTest(case=required_name, invalid=invalid):
                    tree = self.report()
                    case = next(item for item in tree.iter('testcase')
                                if item.get('classname') == f'app.tests.{module}'
                                and item.get('name') == required_name)
                    if invalid == 'missing':
                        next(tree.iter('testsuite')).remove(case)
                    elif invalid == 'replacement':
                        case.set('name', 'unrelated_image_upload_case')
                    else:
                        ET.SubElement(case, invalid)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_model_create_transition_source_cases_and_unrelated_registry_are_frozen(self):
        module = 'test_model_paid_operations_postgres'
        retained = (
            'test_pg_paid_operations_patch_round_trips_typed_rows_and_openapi[dedicated-patch]',
            'test_pg_paid_operations_patch_round_trips_typed_rows_and_openapi[whole-model-patch]',
            'test_pg_paid_operations_invalid_and_cross_factory_patch_leave_family_and_audit_unchanged',
            'test_pg_paid_operations_scoped_save_keeps_other_factory_opaque_legacy_and_other_family',
            'test_pg_usluga_paid_operation_routes_apply_eco_factory_and_typed_sections[usluga-dedicated-patch]',
            'test_pg_usluga_paid_operation_routes_apply_eco_factory_and_typed_sections[usluga-whole-model-patch]',
            'test_pg_paid_operations_failure_rolls_back_then_same_session_retry[audit-failure]',
            'test_pg_paid_operations_failure_rolls_back_then_same_session_retry[postflush-failure]',
            'test_pg_paid_operations_concurrent_factories_serialize_same_family_and_prove_row_lock_wait',
        )
        new_create = (
            'test_pg_model_create_uses_typed_paid_operation_rows_and_keeps_open_metadata[standard-create]',
            'test_pg_model_create_uses_typed_paid_operation_rows_and_keeps_open_metadata[usluga-create]',
            'test_pg_model_create_paid_operation_key_presence_and_scope_merge[omitted-unscoped]',
            'test_pg_model_create_paid_operation_key_presence_and_scope_merge[sparse-row-explicit-null-unscoped]',
            'test_pg_model_create_paid_operation_key_presence_and_scope_merge[snake-scoped]',
            'test_pg_model_create_paid_operation_key_presence_and_scope_merge[camel-scoped]',
            'test_pg_model_create_paid_operation_key_presence_and_scope_merge[both-scoped-canonical-wins]',
            'test_pg_model_create_paid_operation_key_presence_and_scope_merge[snake-null-scoped]',
            'test_pg_model_create_paid_operation_key_presence_and_scope_merge[camel-null-scoped]',
            'test_pg_model_create_paid_operation_key_presence_and_scope_merge[camel-null-unscoped]',
            'test_pg_model_create_keeps_preexisting_opaque_paid_operation_json_readable',
            'test_pg_legacy_variant_create_retains_payload_approval_without_family_sibling',
            'test_pg_model_create_wrong_factory_paid_operation_refuses_before_writes',
            'test_pg_model_create_audit_failure_rolls_back_then_same_session_retry',
            'test_pg_model_create_automatic_number_and_model_rollback_retry_together',
            'test_pg_model_create_variant_waits_for_family_approval_lock',
        )
        manifest = json.loads(Path(gate.__file__).with_name(
            'refactor_pg_required_cases.json').read_text(encoding='utf-8'))
        source = manifest['sources'][module]
        self.assertEqual(source['revision'], '3855f27052e5e32f1bb3908a274e302205101146')
        self.assertEqual(source['git_blob_sha256'],
                         '9256c26ea4493ff70c24ee51f44fe7a054b7172a24fc0a9afe805501c31c34bf')
        self.assertEqual(source['selected_functions'], [
            'test_pg_paid_operations_patch_round_trips_typed_rows_and_openapi',
            'test_pg_paid_operations_invalid_and_cross_factory_patch_leave_family_and_audit_unchanged',
            'test_pg_paid_operations_scoped_save_keeps_other_factory_opaque_legacy_and_other_family',
            'test_pg_usluga_paid_operation_routes_apply_eco_factory_and_typed_sections',
            'test_pg_model_create_uses_typed_paid_operation_rows_and_keeps_open_metadata',
            'test_pg_model_create_paid_operation_key_presence_and_scope_merge',
            'test_pg_model_create_keeps_preexisting_opaque_paid_operation_json_readable',
            'test_pg_legacy_variant_create_retains_payload_approval_without_family_sibling',
            'test_pg_model_create_wrong_factory_paid_operation_refuses_before_writes',
            'test_pg_model_create_audit_failure_rolls_back_then_same_session_retry',
            'test_pg_model_create_automatic_number_and_model_rollback_retry_together',
            'test_pg_model_create_variant_waits_for_family_approval_lock',
            'test_pg_paid_operations_failure_rolls_back_then_same_session_retry',
            'test_pg_paid_operations_concurrent_factories_serialize_same_family_and_prove_row_lock_wait',
        ])
        self.assertEqual(tuple(manifest['cases'][module]), retained[:6] + new_create + retained[6:])
        self.assertEqual(gate.GROUPS[module][0], 25)
        self.assertEqual(sum(len(items) for items in manifest['cases'].values()), 257)
        self.assertEqual(len(manifest['isolated_supplemental_cases']), 17)
        transition = manifest['approved_case_transitions'][0]
        self.assertEqual(transition['removed_required_case'],
                         'test_pg_model_create_keeps_historical_paid_operation_json_opaque')
        self.assertEqual(transition['previous_revision'],
                         '2430deeea65094606de1870560287127c7e6e4fa')
        self.assertEqual(transition['retained_prior_module_case_count'], 9)
        self.assertEqual(transition['replacement_model_create_case_count'], 16)
        self.assertEqual(transition['approved_review_sha256'],
                         'a811298062a2b7eb873eb756b2ab9359c4493cf89f83b582464281607ac1886b')
        self.assertEqual(tuple((receipt['file'], receipt['sha256'], receipt['run'])
                               for receipt in transition['historical_receipts']), (
            ('PR351_CI_PG_ACCEPTANCE_BCAFC730_20261030.json',
             'aaaebcb9996499fae454a57f1560c9a3e732554bfece5752d481f810f5321e26', 41000316321),
            ('PR351_FULL_CI_ACCEPTANCE_BCAFC730_20261030.json',
             'af55735958ef8c3938d513becd6699ed77973c458e924ab07709ae6a4a70fc15', 41000316322),
        ))
        self.assertTrue(all('Historical' in receipt['meaning']
                            for receipt in transition['historical_receipts']))
        self.assertNotIn('test_pg_model_create_keeps_historical_paid_operation_json_opaque',
                         manifest['cases'][module])

        unrelated = {
            'description': manifest['description'],
            'collection_method': manifest['collection_method'],
            'sources': {key: value for key, value in manifest['sources'].items() if key != module},
            'cases': {key: value for key, value in manifest['cases'].items() if key != module},
            'isolated_supplemental_cases': manifest['isolated_supplemental_cases'],
        }
        digest = hashlib.sha256(json.dumps(unrelated, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(digest, '280d087d712f13d194f341ed5d85fd1440a2865af133d556bebe69df89a9d40c')

    def test_each_new_model_create_identity_is_required_and_nonpasses_fail(self):
        module = 'test_model_paid_operations_postgres'
        new_cases = [name for name in gate.REQUIRED_CASES[module]
                     if name.startswith(('test_pg_model_create_uses_typed_paid_operation_rows',
                                         'test_pg_model_create_paid_operation_key_presence',
                                         'test_pg_model_create_keeps_preexisting_opaque',
                                         'test_pg_legacy_variant_create',
                                         'test_pg_model_create_wrong_factory',
                                         'test_pg_model_create_audit_failure',
                                         'test_pg_model_create_automatic_number',
                                         'test_pg_model_create_variant_waits'))]
        self.assertEqual(len(new_cases), 16)
        for required_name in new_cases:
            for invalid in ('replacement', 'skipped', 'failure', 'error'):
                with self.subTest(case=required_name, invalid=invalid):
                    tree = self.report()
                    case = next(item for item in tree.iter('testcase')
                                if item.get('classname') == f'app.tests.{module}'
                                and item.get('name') == required_name)
                    if invalid == 'replacement':
                        case.set('name', 'unrelated_model_create_case')
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
        self.assertEqual(counts['test_bom_add_characterization'], 56)

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

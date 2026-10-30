"""Required isolated refactor PG checks; skips and missing case groups fail.

This runs only with an explicitly supplied approved-instance record. It never
discovers a local server or creates that record from an arbitrary endpoint.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


# Minimum collected counts pin the current parameterized business cases. Adding
# cases is allowed; removing a required case needs an explicit ledger change.
GROUPS = {'test_customer_delete_postgres': (9,
                                   ('test_pg_delete_route_success_repeat_and_missing',
                                    'test_pg_delete_route_auth_denials_preserve_customer',
                                    'test_pg_delete_reference_refusal_preserves_customer',
                                    'test_pg_delete_precommit_failure_rolls_back_then_retry',
                                    'test_pg_delete_distinct_rows_concurrently_preserves_audit_chain')),
 'test_customer_delete_extra_fk_postgres': (3,
                                            ('test_pg_existing_customer_fk_blocks_delete_then_retry',)),
 'test_customer_delete_reference_race_postgres': (2,
                                                  ('test_pg_payment_commit_after_guards_before_delete_flush',
                                                   'test_pg_delete_flush_blocks_payment_until_commit')),
 'test_supplier_update_postgres': (6,
                                   ('test_pg_patch_fields_permissions_and_audit',
                                    'test_pg_inactive_direct_update_remains_out_of_active_list',
                                    'test_pg_concurrent_distinct_suppliers_allow_same_name_and_chain',
                                    'test_pg_precommit_failure_rolls_back_and_retry')),
 'test_customer_update_postgres': (5,
                                   ('test_pg_patch_fields_permissions_and_audit',
                                    'test_pg_precommit_failure_rolls_back_and_retry',
                                    'test_pg_concurrent_distinct_customers_allow_same_name_and_chain')),
 'test_supplier_create_postgres': (7,
                                   ('test_pg_route_saves_all_fields_and_audit_same_session',
                                    'test_pg_route_refuses_unauthenticated_and_forbidden_without_writes',
                                    'test_pg_route_failure_rolls_back_then_retry',
                                    'test_pg_concurrent_suppliers_keep_audit_chain',
                                    'test_pg_create_preserves_raw_fields_duplicates_and_validation')),
 'test_brand_update_postgres': (3,
                                ('test_pg_update_persistence_omission_null_and_chain',
                                 'test_pg_duplicate_and_audit_finalize_failure_roll_back_then_retry',
                                 'test_pg_case_variant_update_is_allowed')),
 'test_customer_create_postgres': (6,
                                   ('test_pg_route_saves_all_fields_and_audit_same_session',
                                    'test_pg_route_refuses_unauthenticated_and_forbidden_without_writes',
                                    'test_pg_route_failure_rolls_back_then_retry',
                                    'test_pg_concurrent_customers_keep_audit_chain')),
 'test_brand_create_postgres': (2,
                                ('test_pg_create_duplicate_and_audit',
                                 'test_pg_audit_failure_rolls_back_then_retry')),
 'test_planning_alternate_creation_postgres': (14,
                                               ('test_pg_alternate_create_and_existing_order_handoff',
                                                'test_pg_alternate_optional_material_printing_and_full_children',
                                                'test_pg_shared_production_writer_keeps_client_general_and_usluga_callers',
                                                'test_pg_alternate_missing_and_closed_orders_refused',
                                                'test_pg_alternate_postflush_and_audit_failure_rollback_retry',
                                                'test_pg_alternate_commit_failure_rolls_back_audit_and_retries_same_session',
                                                'test_pg_alternate_concurrent_implicit_orders_witness_number_lock_chain')),
 'test_purchase_conversion_postgres': (7, ()),
 'test_bom_add_characterization': (55, ()),
 'test_forecast_review_postgres': (9, ()),
 'test_stock_movement_and_reservation_postgres': (7, ()),
 'test_sales_update_old_behavior': (4,
                                    ('test_pg_stale_unchanged_status_cannot_rewind_concurrent_workflow',
                                     'test_pg_edit_and_audit_rollback_together_then_retry',
                                     'test_pg_unknown_customer_fails_fk_atomically_without_custom_service_refusal')),
 'test_finance_sales_invoice_generation': (5,
                                           ('test_sales_generation_pg_failure_rolls_back_invoice_and_audit_then_retry',
                                            'test_sales_generation_pg_serializes_two_issuers_of_one_order',
                                            'test_sales_generation_pg_and_manual_entry_points_share_one_invoice')),
 'test_invoice_creation_integrity': (4,
                                     ('test_concurrent_same_entry_point_creates_exactly_one_invoice',
                                      'test_concurrent_mixed_entry_points_create_exactly_one_invoice',
                                      'test_concurrent_creation_does_not_duplicate_invoice_numbers')),
 'test_customer_invoice_creation_race': (10, ()),
 'test_stock_batch_edit_postgres': (9,
                                    ('test_pg_update_batch_nullable_patch_quantity_warehouse_and_movement_conservation',
                                     'test_pg_forced_batch_item_relink_updates_catalog_and_inventory_participants',
                                     'test_pg_batch_edit_refusals_leave_all_rows_and_audit_unchanged',
                                     'test_pg_audit_failure_rolls_back_all_batch_edit_participants_then_one_retry')),
 'test_finance_payment_output_postgres': (6,
                                          ('test_pg_typed_payment_concurrent_retries',
                                           'test_pg_typed_payment_other_user_key_is_independent',
                                           'test_pg_typed_payment_rollback_releases_retry_lock')),
 'test_collection_update_postgres': (2,
                                     ('test_pg_update_preserves_omissions_and_legacy_status_then_clears_nullables',
                                      'test_pg_audit_finalization_failure_rolls_back_then_retry')),
 'test_price_calculation_purchasing_postgres': (2,
                                                ('test_pg_purchasing_completion_transition_recipients_and_audit_actor',
                                                 'test_pg_purchasing_request_audit_and_notification_rollback_then_retry')),
 'test_package_print_run_postgres': (7,
                                     ('test_print_run_persistence_roundtrips_on_approved_postgres',
                                      'test_selected_print_run_same_key_replays_and_changed_body_refuses',
                                      'test_selected_print_run_route_role_denial_has_no_writes',
                                      'test_selected_print_run_foreign_department_denial_has_no_writes',
                                      'test_selected_print_run_failure_rolls_back_then_retry',
                                      'test_selected_print_run_same_key_concurrency_serializes_exactly_once')),
 'test_purchase_receipt_persistence_postgres': (6,
                                                ('test_pg_route_permission_denial_has_no_receipt_writes',
                                                 'test_pg_receipt_participant_command_qc_type_is_canonical',
                                                 'test_pg_receipt_audit_and_idempotency_failure_rolls_back_then_retry_succeeds',
                                                 'test_pg_receipt_replay_rechecks_inventory_access_before_serving_saved_response',
                                                 'test_pg_receipt_same_and_different_key_workers_serialize_on_purchase_order')),
 'test_payroll_adjustment_create_postgres': (2,
                                             ('test_approved_pg_adjustment_writer_serializes_before_period_lock',
                                              'test_approved_pg_manual_adjustment_flush_and_audit_failure_roll_back')),
 'test_shipment_reopen_invoice_postgres': (4,
                                           ('test_pg_shipment_reopen_finance_participant_same_session_and_no_early_commit',
                                            'test_pg_shipment_reopen_preflights_every_invoice_before_any_finance_write',
                                            'test_pg_shipment_reopen_audit_failure_rolls_back_and_retry_commits_all',
                                            'test_pg_invoice_payment_and_shipment_reopen_serialize_on_invoice_row')),
 'test_model_paid_operations_postgres': (25,
                                         ('test_pg_paid_operations_patch_round_trips_typed_rows_and_openapi',
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
                                          'test_pg_paid_operations_concurrent_factories_serialize_same_family_and_prove_row_lock_wait')),
 'test_direct_finished_goods_reserve_postgres': (6,
                                                 ('test_pg_direct_reserve_manual_package_persists_rows_and_audit',
                                                  'test_pg_direct_reserve_denied_actor_makes_no_business_writes',
                                                  'test_pg_direct_reserve_competing_piece_requests_do_not_oversell',
                                                  'test_pg_direct_reserve_failure_rolls_back_then_retry')),
 'test_support_settings_postgres': (16, ('test_pg_section_merge_waits_on_exact_missing_or_existing_lock', 'test_pg_logo_update_waits_on_shared_company_info_lock', 'test_pg_existing_row_wait_refreshes_after_preexisting_row_lock', 'test_pg_settings_failure_rolls_back_and_retry_persists_once', 'test_pg_typed_route_persists_wire_defaults_null_and_audit', 'test_pg_typed_route_denials_invalid_and_unknown_have_no_writes', 'test_pg_typed_route_uses_schema_writer_session_and_one_commit')),
 'test_model_image_upload_postgres': (25, ('test_upload_image_type_preserves_null_and_normalization_contract',
                                           'test_upload_image_type_rejects_values_outside_the_action_subset',
                                           'test_upload_form_openapi_exposes_enum_contract_for_both_catalog_scopes',
                                           'test_upload_response_openapi_preserves_exact_two_key_contract',
                                           'test_upload_response_dto_has_exact_two_key_json_contract',
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
                                           'test_pg_upload_scope_is_rechecked_in_worker_before_mapped_insert')),
 'test_sewing_output_postgres': (20,
                                 ('test_pg_factory_output_persists_all_participants_and_replays_once',
                                  'test_pg_band_output_uses_the_same_operation_and_preserves_retry_contract',
                                  'test_pg_sewing_output_refusals_have_no_persistent_effects',
                                  'test_pg_real_accessory_gate_refusal_rolls_back_flushed_block_then_retry',
                                  'test_pg_zero_defect_output_does_not_create_waste_or_advance_its_sequence',
                                  'test_pg_work_order_status_filter_uses_enum_and_wire_value',
                                  'test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds',
                                  'test_pg_sewing_output_waits_on_real_work_order_lock',
                                  'test_pg_band_output_waits_on_same_work_order_lock')),
 'test_task_create_postgres': (11,
                               ('test_pg_task_create_self_and_single_assignment_share_session_and_audit',
                                'test_pg_task_broadcast_is_bounded_active_ordered_and_atomic',
                                'test_pg_task_create_denials_leave_no_task_notification_or_audit',
                                'test_pg_task_create_failure_after_flush_or_audit_commit_rolls_back_then_retry',
                                'test_pg_repeated_identical_task_create_requests_remain_distinct',
                                'test_pg_task_broadcast_refuses_when_authenticated_actor_becomes_inactive_before_recipient_select',
                                'test_pg_concurrent_task_creates_keep_audit_chain')),
 'test_task_update_postgres': (15,
                               ('test_pg_task_patch_reassignment_notification_audit_and_shared_session',
                                'test_pg_task_patch_denials_preserve_task_notifications_and_audit',
                                'test_pg_task_patch_preserves_omission_nullable_values_and_completion_time',
                                'test_pg_task_patch_explicit_null_not_null_fields_keep_database_failure_semantics',
                                'test_pg_task_patch_failure_rolls_back_then_retry',
                                'test_pg_task_patch_concurrent_disjoint_fields_merge_with_two_audits',
                                'test_pg_task_patch_repeat_has_no_idempotency_or_repeat_assignment_notice')),
 'test_task_complete_postgres': (15,
                                 ('test_pg_task_complete_actor_notification_audit_and_shared_session',
                                  'test_pg_task_complete_does_not_notify_without_distinct_creator',
                                  'test_pg_task_complete_denials_preserve_all_task_effects',
                                  'test_pg_task_complete_missing_row_precedes_actor_authorization',
                                  'test_pg_task_complete_http_failure_rolls_back_then_fresh_request_retry',
                                  'test_pg_task_complete_same_session_rollback_clears_audit_state_then_retry',
                                  'test_pg_task_complete_repeat_resets_timestamp_and_duplicates_notice_and_audit',
                                  'test_pg_task_complete_concurrent_calls_remain_distinct_without_deduplication')),
 'test_task_delete_postgres': (11,
                               ('test_pg_task_delete_creator_and_manager_share_session_audit_and_keep_notice',
                                'test_pg_task_delete_denials_preserve_task_notice_audit_and_commit_state',
                                'test_pg_task_delete_missing_row_precedes_authorization_without_writes',
                                'test_pg_task_delete_failure_rolls_back_and_retries_on_same_session',
                                'test_pg_task_delete_two_authorized_sessions_keep_current_duplicate_request_semantics')),
 'test_accessory_issue_postgres': (14,
                                   ('test_pg_route_stock_issue_persists_fifo_gate_and_audit_same_session',
                                    'test_pg_route_manual_issue_records_without_stock_or_movement',
                                    'test_pg_route_permission_denials_leave_business_and_audit_rows_unchanged',
                                    'test_pg_repeated_manual_issue_posts_keep_existing_no_idempotency_behavior',
                                    'test_pg_duplicate_stock_lines_keep_current_preloop_bom_limit_check',
                                    'test_pg_route_refusals_leave_issue_rows_stock_gate_and_audit_unchanged',
                                    'test_pg_issue_failure_rolls_back_and_retries_on_same_session',
                                    'test_pg_issue_batch_lock_prevents_physical_oversell_with_observed_blocker'))}
REQUIRED_CASES = json.loads(
    Path(__file__).with_name("refactor_pg_required_cases.json").read_text(encoding="utf-8")
)["cases"]
REQUIRED_SOURCES = json.loads(
    Path(__file__).with_name("refactor_pg_required_cases.json").read_text(encoding="utf-8")
)["sources"]

_MODEL_IMAGE_UPLOAD_MODULE = "test_model_image_upload_postgres"
_MODEL_IMAGE_UPLOAD_REVISION = "ee2e8f01313e6f637fe842a5b6e5f8e1608b5165"
_MODEL_IMAGE_UPLOAD_BLOB_OID = "38ce2a27b5c0121318af52c843686cbd7eac0ccc"
_MODEL_IMAGE_UPLOAD_BLOB_SHA256 = "47e9e840c08f6225eb943e949c73678e21a6a0f9d882fda1d75e23e0e31ee1c1"
_MODEL_IMAGE_UPLOAD_FUNCTIONS = (
    "test_upload_image_type_preserves_null_and_normalization_contract",
    "test_upload_image_type_rejects_values_outside_the_action_subset",
    "test_upload_form_openapi_exposes_enum_contract_for_both_catalog_scopes",
    "test_upload_response_openapi_preserves_exact_two_key_contract",
    "test_upload_response_dto_has_exact_two_key_json_contract",
    "test_pg_upload_form_rejects_unknown_enum_before_storage_or_rows",
    "test_pg_upload_persists_typed_image_through_worker_session_and_audits_once",
    "test_pg_upload_route_permission_denial_writes_nothing",
    "test_pg_upload_pattern_type_keeps_nonprimary_contract",
    "test_pg_upload_null_type_preserves_existing_primary",
    "test_pg_document_upload_persists_one_managed_file_without_thumbnails",
    "test_pg_document_upload_precommit_audit_failure_rolls_back_row_and_file",
    "test_pg_document_upload_partial_write_failure_leaves_no_file_or_row",
    "test_pg_cancel_after_worker_commit_keeps_file_and_row",
    "test_pg_cancel_during_image_processing_cleans_files_before_database_write",
    "test_pg_upload_scope_is_rechecked_in_worker_before_mapped_insert",
)
_BOM_UPDATE_MODULE = "test_bom_add_characterization"
_BOM_UPDATE_REVISION = "52102d4764544e0906f24630f434377b7e7ac259"
_BOM_UPDATE_BLOB_OID = "812d64c8baf12c812b83f8d8f8968bace1fba442"
_BOM_UPDATE_BLOB_SHA256 = "eb92b3c28e49b7e77f94452bdaed5e2b008a59716d0052d0b38220a21cecc150"
_BOM_UPDATE_FUNCTIONS = (
    "test_manual_normalizes_role_name_and_discards_stale_references",
    "test_manual_invalid_role_is_currently_service400_and_no_write",
    "test_inventory_link_ignores_supplied_role_and_whitespace_name",
    "test_inventory_role_length_still_validated_before_normalization",
    "test_standard_fabric_discards_nonexistent_batch_and_fills_blank_unit",
    "test_usluga_disallows_inventory_fabric_and_nonaccessory_categories",
    "test_batch_link_defaults_and_explicit_overrides",
    "test_reference_and_photo_failures_do_not_write",
    "test_batch_must_belong_to_selected_item",
    "test_wrong_catalog_scope_is404",
    "test_permission_revocation_is_enforced",
    "test_usluga_requires_selected_eco_factory",
    "test_existing_numeric_policy_and_pg_rounding_preserved",
    "test_second_main409_secondary_repeated_and_other_model_main_allowed",
    "test_patch_uses_canonical_roles_and_output_keeps_legacy_projection",
    "test_patch_late_audit_failure_rolls_back_and_same_session_retry",
    "test_clone_and_variant_copy_roles_without_calling_add_bom",
    "test_same_session_audit_outer_commit_and_precommit_invisibility",
    "test_real_audit_failure_rolls_back_bom_and_audit",
    "test_actual_migration_checks_reject_invalid_storage",
    "test_nullable_sql_check_is_not_a_nonnull_role_guarantee",
    "test_competing_main_creates_reach_unique_index_one_business_outcome",
    "test_post_openapi_nullable_canonical_role_and_id_only_wire",
    "test_blanket_strict_role_mutation_would_break_inventory_compatibility",
)
_COMBINED_CASE_SHA256 = {
    "test_planning_alternate_creation_postgres": "c09a220c6581ca4c4e6f9f70b5077ebd4d14d08c336dcd0e86ed924815df60ed",
    "test_sewing_output_postgres": "250516d66f65a2f8b58a585a8bba42186ba5b894e2a666d5f1ab0a10f1a0701b",
    "test_task_create_postgres": "7bdf2d0674e5d53429b12c7d9df62285f0173334398ea06248d382b2a25809ca",
    "test_task_update_postgres": "634f674398e6ecfbc64a9182377502154a1d288472de97278acf1dcf3b7e5283",
    "test_task_complete_postgres": "1d71a979423c645da4366572a8437771306a12047a897b482cad413fbac0f05c",
    "test_task_delete_postgres": "6a110490d8cc0ce3eddad9af2a20fdb2b42220318d44f5ae9b7d9d7174881fad",
    "test_accessory_issue_postgres": "7c2d430610b5c37c1db5650055ddbd94f321e938624305b8c8266f02ab6b78a7",
}
_COMBINED_SOURCE_PINS = {
    "test_planning_alternate_creation_postgres": (
        "a93021ff77392f5748563a48e8f98813c635f7f5", "08c60cdd2e8c946223c31ee76b16abc66373520a", "b66fa4b8b08533dc6da6515f01a77deb601fcbccfe95d84f7e134399d17b2620"),
    "test_sewing_output_postgres": (
        "a93021ff77392f5748563a48e8f98813c635f7f5", "99950fb85b394e32e95035e0ad8f258f7963b6db", "a5e7f9aa5a9f2488078bca6a8fb2218501aceb9de8d7cf579c0606e3644fc050"),
    "test_task_create_postgres": (
        "a93021ff77392f5748563a48e8f98813c635f7f5", "518eae9a7c6b54f46211b065f00613afb0e92ae3", "d698d8f4f013ca9c7143ef4e45aad655e0a21dd67227e883aea4b39ac2ab12e8"),
    "test_task_update_postgres": (
        "a93021ff77392f5748563a48e8f98813c635f7f5", "b7d5edd931ae72a74c050aa548e758eb871994db", "37d85902e1bb0eae228ac8928eb9372816bde7f24c1f5e03e7912345d705234e"),
    "test_task_complete_postgres": (
        "a93021ff77392f5748563a48e8f98813c635f7f5", "355d0a9d76656281a4b947d11a654aa5b9121eb6", "27483adb76a148d9456f73c2505f6637e70b291e8e1c6f84a82fc3819967ab5f"),
    "test_task_delete_postgres": (
        "a93021ff77392f5748563a48e8f98813c635f7f5", "628aba150eb3e62e4ffe2784954a664c2965c744", "1d0fcdbd22a0dc7a3e5608ca19a67b96bfb48da6e7303963768955e5bbcdaf1d"),
    "test_accessory_issue_postgres": (
        "0a15bb8dc1f194fb2c29d7b605dc827c13805d92", "a5b3ef6090393d69b33e7aa505b3e5741e47446d", "a9940a0ada598de3e95486750e3e17c6354479f528de5e8bf45958489a2c40ef"),
}


def required_nodes() -> list[str]:
    result = []
    for module, (_, names) in GROUPS.items():
        path = f"app/tests/{module}.py"
        if names:
            result.extend(f"{path}::{name}" for name in names)
        else:
            result.append(path)
    return result


def verify_model_image_upload_source() -> None:
    """Verify the pinned source from Git objects without resolving HEAD/history."""
    source = REQUIRED_SOURCES.get(_MODEL_IMAGE_UPLOAD_MODULE)
    if (not source
            or source.get("revision") != _MODEL_IMAGE_UPLOAD_REVISION
            or source.get("git_blob_oid") != _MODEL_IMAGE_UPLOAD_BLOB_OID
            or source.get("git_blob_sha256") != _MODEL_IMAGE_UPLOAD_BLOB_SHA256
            or tuple(source.get("selected_functions", ())) != _MODEL_IMAGE_UPLOAD_FUNCTIONS):
        raise ValueError("required Model image-upload source manifest pin changed")

    repo = Path(__file__).resolve().parents[1]
    relative_path = f"backend/app/tests/{_MODEL_IMAGE_UPLOAD_MODULE}.py"
    blob = subprocess.run(
        ["git", "cat-file", "blob", _MODEL_IMAGE_UPLOAD_BLOB_OID],
        cwd=repo, check=True, stdout=subprocess.PIPE,
    ).stdout
    if hashlib.sha256(blob).hexdigest() != _MODEL_IMAGE_UPLOAD_BLOB_SHA256:
        raise ValueError("required Model image-upload Git blob hash changed")

    module = ast.parse(blob.decode("utf-8"), filename=relative_path)
    functions = tuple(
        node.name for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    )
    if functions != _MODEL_IMAGE_UPLOAD_FUNCTIONS:
        raise ValueError("required Model image-upload test function identities changed")

    worktree_oid = subprocess.run(
        ["git", "hash-object", f"--path={relative_path}", "--", relative_path],
        cwd=repo, check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()
    if worktree_oid != _MODEL_IMAGE_UPLOAD_BLOB_OID:
        raise ValueError("Model image-upload worktree file differs from its pinned Git blob")


def verify_bom_update_source() -> None:
    """Verify the BOM characterization source from pinned Git objects only."""
    source = REQUIRED_SOURCES.get(_BOM_UPDATE_MODULE)
    if (not source
            or source.get("revision") != _BOM_UPDATE_REVISION
            or source.get("git_blob_oid") != _BOM_UPDATE_BLOB_OID
            or source.get("git_blob_sha256") != _BOM_UPDATE_BLOB_SHA256
            or tuple(source.get("selected_functions", ())) != _BOM_UPDATE_FUNCTIONS):
        raise ValueError("required BOM characterization source manifest pin changed")

    repo = Path(__file__).resolve().parents[1]
    relative_path = f"backend/app/tests/{_BOM_UPDATE_MODULE}.py"
    blob = subprocess.run(
        ["git", "cat-file", "blob", _BOM_UPDATE_BLOB_OID],
        cwd=repo, check=True, stdout=subprocess.PIPE,
    ).stdout
    if hashlib.sha256(blob).hexdigest() != _BOM_UPDATE_BLOB_SHA256:
        raise ValueError("required BOM characterization Git blob hash changed")

    module = ast.parse(blob.decode("utf-8"), filename=relative_path)
    functions = tuple(
        node.name for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    )
    if functions != _BOM_UPDATE_FUNCTIONS:
        raise ValueError("required BOM characterization test function identities changed")

    worktree_oid = subprocess.run(
        ["git", "hash-object", f"--path={relative_path}", "--", relative_path],
        cwd=repo, check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()
    if worktree_oid != _BOM_UPDATE_BLOB_OID:
        raise ValueError("BOM characterization worktree file differs from its pinned Git blob")


def verify_combined_registration_sources() -> None:
    """Pin the integrated Planning, Sewing, Task and accessory case union."""
    repo = Path(__file__).resolve().parents[1]
    for module, (revision, blob_oid, blob_sha256) in _COMBINED_SOURCE_PINS.items():
        source = REQUIRED_SOURCES.get(module)
        functions = GROUPS[module][1]
        cases = REQUIRED_CASES.get(module, ())
        if (not source
                or source.get("revision") != revision
                or source.get("git_blob_oid") != blob_oid
                or source.get("git_blob_sha256") != blob_sha256
                or tuple(source.get("selected_functions", ())) != functions):
            raise ValueError(f"required combined source manifest pin changed: {module}")
        case_hash = hashlib.sha256(
            json.dumps(list(cases), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if case_hash != _COMBINED_CASE_SHA256[module]:
            raise ValueError(f"required combined case identities changed: {module}")

        relative_path = f"backend/app/tests/{module}.py"
        blob = subprocess.run(
            ["git", "cat-file", "blob", blob_oid], cwd=repo, check=True,
            stdout=subprocess.PIPE,
        ).stdout
        if hashlib.sha256(blob).hexdigest() != blob_sha256:
            raise ValueError(f"required combined Git blob hash changed: {module}")
        parsed = ast.parse(blob.decode("utf-8"), filename=relative_path)
        actual_functions = tuple(
            node.name for node in parsed.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
        if actual_functions != functions:
            raise ValueError(f"required combined test functions changed: {module}")
        worktree_oid = subprocess.run(
            ["git", "hash-object", f"--path={relative_path}", "--", relative_path],
            cwd=repo, check=True, stdout=subprocess.PIPE, text=True,
        ).stdout.strip()
        if worktree_oid != blob_oid:
            raise ValueError(f"combined source differs from pinned Git blob: {module}")


def check_report(report: Path) -> dict[str, int]:
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
    for module, (minimum, names) in GROUPS.items():
        selected = [case for case in cases if case.get("classname", "").split(".")[-1] == module]
        counts[module] = len(selected)
        if len(selected) < minimum:
            raise ValueError(f"required PG group {module}: {len(selected)} cases, expected at least {minimum}")
        for name in names:
            if not any(case.get("name", "").split("[", 1)[0] == name for case in selected):
                raise ValueError(f"required PG function missing: {module}.{name}")
        actual_names = {case.get("name", "") for case in selected}
        missing = set(REQUIRED_CASES[module]) - actual_names
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci-identity", type=Path)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--report", type=Path, default=Path("refactor-pg-gate.xml"))
    args = parser.parse_args()
    if args.ci_identity:
        if not args.github_env:
            parser.error("--ci-identity requires --github-env")
        configure_ci(args.ci_identity, args.github_env)
        return 0
    if os.environ.get("MILANA_REQUIRE_TEST_PG") != "1" or not os.environ.get("MILANA_TEST_PG_INSTANCE"):
        parser.error("required PG gate needs MILANA_REQUIRE_TEST_PG=1 and explicit approved instance")
    try:
        verify_model_image_upload_source()
        verify_bom_update_source()
        verify_combined_registration_sources()
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, ValueError) as exc:
        parser.error(f"required test source verification failed: {exc}")
    report = args.report.resolve()
    # Never accept a stale report after a failed or interrupted pytest process.
    if report.exists():
        parser.error("report path already exists; choose a fresh report path")
    backend = Path(__file__).resolve().parents[1] / "backend"
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               *required_nodes(), f"--junitxml={report}"]
    with tempfile.TemporaryDirectory(prefix="milana-pg-env-") as scratch:
        env = sanitized_pg_environment(dict(os.environ), Path(scratch))
        completed = subprocess.run(command, cwd=backend, check=False, timeout=1800, env=env)
    if completed.returncode:
        return completed.returncode
    counts = check_report(report)
    print(json.dumps({"required_pg_gate": "PASS", "passed_case_counts": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

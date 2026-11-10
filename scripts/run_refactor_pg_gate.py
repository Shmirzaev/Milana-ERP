"""Required isolated refactor PG checks; skips and missing case groups fail.

This runs only with an explicitly supplied approved-instance record. It never
discovers a local server or creates that record from an arbitrary endpoint.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from refactor_pg_evidence import (
    check_required_report,
    configure_ci as configure_ci,
    sanitized_pg_environment as sanitized_pg_environment,
)


# Minimum collected counts pin the current parameterized business cases. Adding
# cases is allowed; removing a required case needs an explicit ledger change.
GROUPS = {
    'test_variant_price_workflow_postgres': (4, (
        'test_pg_concurrent_creation_one_slot_audit_and_team_notice',
        'test_pg_parallel_submissions_retry_once_and_single_finance_notification',
        'test_pg_approval_race_one_price_and_audit_and_atomic_rollback',
        'test_pg_source_change_makes_pending_approval_stale',
    )),
    'test_waste_receive_commit_postgres': (4, ('test_signed_receive_refusals_and_retained_readback', 'test_signed_receipt_finalization_commit_rollback_retry', 'test_signed_receipt_observed_wait_one_transition')),
    'test_price_calculation_finance_postgres': (4, ('test_signed_finance_refusal_omission_null_and_attachment', 'test_signed_finance_rollback_and_retry', 'test_concurrent_finance_updates_wait_and_last_writer_wins')),
    'test_modelsize_delete_postgres': (8, ('test_delete_readback_and_audit', 'test_deferred_commit_failure_rolls_back_and_retry', 'test_signed_scope_permissions_missing_and_retained_state', 'test_signed_audit_finalization_failure_rolls_back_and_retry', 'test_last_size_with_issued_bundle_preserves_bundle', 'test_delete_and_same_label_insert_interleave_without_unique_guard')),
    'test_price_calculation_cutting_postgres': (3, ('test_signed_failure_rollback_and_retry', 'test_signed_passport_manual_refusals_and_readback', 'test_concurrent_passport_update_uses_visible_committed_snapshot')),
    'test_price_calculation_accessory_postgres': (3, ('test_signed_accessory_transitions_and_retained_readback', 'test_signed_failure_rollback_and_retry', 'test_concurrent_unlocked_updates_characterize_stale_completion')),
    'test_model_delete_postgres': (14, ('test_pg_signed_delete_scope_and_retained_readback', 'test_pg_signed_delete_unguarded_forecast_fk_rollback', 'test_pg_signed_delete_finalization_and_deferred_commit_rollback_retry', 'test_pg_signed_delete_real_reference_guards_in_order', 'test_pg_delete_blocks_concurrent_sales_reference_then_fk_refuses')),
    'test_price_calculation_creation_postgres': (8, ('test_pg_signed_creation_auth_duplicates_and_recipients', 'test_pg_signed_creation_margin_contract', 'test_pg_signed_creation_failure_teardown_retry')),
    'test_price_calculation_status_postgres': (1, ('test_pg_signed_status_transitions_finance_gate_and_notifications',)),
    'test_price_calculation_purchasing_postgres': (2, ('test_pg_purchasing_completion_transition_recipients_and_audit_actor', 'test_pg_purchasing_request_audit_and_notification_rollback_then_retry')),

    'test_model_create_commit_postgres': (7, ('test_pg_signed_create_auth_scope_and_retained_readback', 'test_pg_variant_inherits_approval_without_changing_family_or_other_scope', 'test_pg_create_finalization_and_deferred_commit_rollback_retry', 'test_pg_create_serializes_on_numbering_and_family_lock')),
    'test_waste_race_rollback_postgres': (2, ('test_waste_sale_postgres_contending_http_requests', 'test_waste_sale_postgres_audit_finalization_rollback')),
    'test_waste_sale_commit_postgres': (3, ('test_pg_sale_deferred_commit_failure_rolls_back_replay_then_retry', 'test_pg_sale_auth_partial_then_exhaust_and_replay', 'test_pg_sale_same_key_service_race_serializes_and_replays')),
    'test_waste_sale_list_postgres': (4, ('test_pg_empty_filtered_list_has_no_sale_query', 'test_pg_list_batch_history_filters_auth_and_no_writes', 'test_pg_partial_sale_remaining_stale_and_exhaustion', 'test_pg_nan_original_service_diagnostic')),

    'test_waste_reject_postgres': (17, ('test_pg_reject_refuses_request_before_invalid_parent', 'test_pg_reject_refuses_invalid_parent', 'test_pg_reject_recovers_invalid_historical_parent', 'test_pg_reject_orphan_creation_fk_refusal_then_existing_request', 'test_pg_reject_auth_refusal_audit_failure_retry', 'test_pg_reject_deferred_commit_failure_retry', 'test_pg_rejection_race_serializes_on_parent')),
    'test_waste_approve_postgres': (16, ('test_pg_approve_refuses_request_before_invalid_parent', 'test_pg_approve_refuses_invalid_parent', 'test_pg_approve_refuses_invalid_waste', 'test_pg_approve_auth_refusal_audit_failure_retry', 'test_pg_approve_deferred_commit_failure_retry', 'test_pg_approval_race_serializes_on_parent')),
    'test_waste_mark_disposed_postgres': (15, ('test_pg_mark_refuses_request_before_invalid_parent', 'test_pg_mark_refuses_nonapproved_parent', 'test_pg_mark_refuses_invalid_waste', 'test_pg_mark_disposed_auth_refusal_audit_failure_retry', 'test_pg_mark_disposed_deferred_commit_failure_retry', 'test_pg_mark_disposed_race_serializes_on_parent')),
    'test_waste_disposal_integrity': (4, ('test_postgres_concurrent_disposal_has_one_effect_and_refreshes_cached_state',)),
    "test_waste_request_postgres": (3, ('test_pg_disposal_http_refusal_and_audit_failure_retry', 'test_pg_disposal_deferred_commit_failure_retry', 'test_pg_disposal_request_race_serializes_on_parent')),
    "test_waste_manual_create_commit_postgres": (2, ('test_pg_manual_create_commit_abort_rolls_back_then_retry', 'test_pg_unicode_create_and_all_typed_status_filters_round_trip')),
    "test_stocktake_scan_postgres": (5, ('test_pg_scan_auth_duplicate_first_evidence_and_completed_refusal', 'test_pg_scan_request_audit_finalization_failure_then_retry', 'test_pg_scan_expected_unexpected_package_and_refusals', 'test_pg_duplicate_package_scan_waits_on_first_parent_lock', 'test_pg_scan_deferred_commit_abort_preserves_evidence_then_retry')),
    "test_stocktake_undo_postgres": (6, (
        'test_pg_undo_auth_and_selection_refusal_before_mutation',
        'test_pg_undo_request_audit_finalization_failure_then_retry',
        'test_pg_undo_duplicate_and_foreign_selection_and_single_success',
        'test_pg_undo_completed_count_refuses_without_mutation',
        'test_pg_undo_waits_for_completion_with_preloaded_count',
    )),
    "test_stocktake_create_postgres": (4, (
        "test_pg_http_create_auth_and_request_key_replay",
        "test_pg_same_key_concurrent_create_replays_unique_winner",
        "test_pg_request_audit_finalization_failure_rolls_back_then_retry",
        "test_pg_deferred_create_commit_abort_rolls_back_then_retry",
    )),
    "test_stocktake_delete_postgres": (5, (
        'test_pg_request_audit_flush_failure_rolls_back_bulk',
        'test_pg_overlapping_bulk_deletes_serialize',
        'test_pg_deferred_commit_failure_restores_bulk',
        'test_pg_delete_blocks_scan_or_completion',
    )),
    'test_identity_access_catalog': (20, ('test_catalog_authentication_and_permission_refusals', 'test_catalog_retains_order_labels_and_grantability_without_writes', 'test_direct_service_rejects_inactive_privileged_actor', 'test_direct_service_rejects_stale_deactivated_actor', 'test_direct_service_rejects_unprivileged_actor')),
    'test_identity_access_preview': (30, ('test_direct_service_rejects_inactive_privileged_actor', 'test_direct_service_rejects_stale_deactivated_actor', 'test_direct_service_rejects_unprivileged_actor', 'test_preview_expands_wildcard_without_saving_or_enforcing_grant_rights', 'test_preview_primary_denies_secondary_grants_and_empty_factories', 'test_preview_refusal_order_and_no_writes', 'test_super_admin_subject_is_available_in_every_factory')),
    'test_identity_admin_user_list': (20, ('test_direct_service_rejects_inactive_privileged_actor', 'test_direct_service_rejects_stale_deactivated_actor', 'test_direct_service_rejects_unprivileged_actor', 'test_list_authentication_and_permission_refusals', 'test_list_includes_inactive_other_factory_and_protected_accounts_in_id_order')),
    'test_identity_admin_user_get': (24, ('test_direct_service_rejects_inactive_privileged_actor', 'test_direct_service_rejects_stale_deactivated_actor', 'test_direct_service_rejects_unprivileged_actor', 'test_lookup_permission_before_missing_target', 'test_lookup_retains_output_and_allows_inactive_other_factory_target')),
    'test_identity_admin_user_update': (108, ('test_admin_password_rotates_cutoff_and_unused_reset_links_in_same_commit', 'test_cannot_remove_last_active_super_or_wildcard_admin', 'test_direct_service_rejects_inactive_privileged_actor', 'test_direct_service_rejects_stale_deactivated_actor', 'test_direct_service_rejects_unprivileged_actor', 'test_duplicate_email_failure_preserves_user_and_audit', 'test_empty_password_and_omitted_fields_keep_credentials_but_still_audit', 'test_inactive_guard_does_not_flush_pending_changes', 'test_manager_inventory_scope_cannot_be_removed_from_another_account', 'test_manager_updates_email_access_and_activation_atomically_with_audit', 'test_missing_target_after_authentication_and_permission', 'test_non_super_manager_cannot_edit_any_protected_administrator_form', 'test_password_change_rejects_old_bearer_and_accepts_new_bearer', 'test_patch_refusal_order_and_rollback', 'test_precommit_failure_rolls_back_user_credentials_links_and_audit_then_retry', 'test_super_admin_changes_factory_and_revokes_old_session')),
    'test_identity_admin_user_delete': (80, ('test_active_wildcard_actor_cannot_delete_protected_super_admin', 'test_audit_history_blocks_deletion_without_touching_any_references', 'test_authentication_and_permission_precede_missing_target', 'test_delete_unused_user_detaches_nullable_deletes_required_refs_and_audits_once', 'test_direct_service_rejects_inactive_privileged_actor', 'test_direct_service_rejects_stale_deactivated_actor', 'test_direct_service_rejects_unprivileged_actor', 'test_explicit_super_without_wildcard_can_delete_nonfinal_protected_account', 'test_last_wildcard_admin_refusal_precedes_history_check', 'test_non_super_manager_cannot_delete_protected_forms_before_history_cleanup', 'test_precommit_failure_rolls_back_deletion_all_refs_and_audit_then_retry', 'test_self_deletion_refused_before_protection_and_audit_history')),
    "test_batch_restore_postgres": (2, ("test_pg_batch_restore_audit_failure_rolls_back", "test_pg_batch_restore_concurrent_duplicate_serializes")),
    "test_waste_create_receive_postgres": (2, ("test_waste_create_receive_audit_failure_rolls_back_then_retry",)),
    "test_waste_receipt_race_characterization_postgres": (1, ("test_receipt_concurrent_observed_recorded_characterization",)),
    "test_customer_receipt_http_postgres": (2, ()),
    'test_customer_delete_postgres': (9, ('test_pg_delete_route_success_repeat_and_missing', 'test_pg_delete_route_auth_denials_preserve_customer', 'test_pg_delete_reference_refusal_preserves_customer', 'test_pg_delete_precommit_failure_rolls_back_then_retry', 'test_pg_delete_distinct_rows_concurrently_preserves_audit_chain')),
    'test_customer_delete_extra_fk_postgres': (3, ('test_pg_existing_customer_fk_blocks_delete_then_retry',)),
    'test_customer_delete_reference_race_postgres': (2, ('test_pg_payment_commit_after_guards_before_delete_flush', 'test_pg_delete_flush_blocks_payment_until_commit')),
    "test_supplier_update_postgres": (6, ('test_pg_patch_fields_permissions_and_audit', 'test_pg_inactive_direct_update_remains_out_of_active_list', 'test_pg_concurrent_distinct_suppliers_allow_same_name_and_chain', 'test_pg_precommit_failure_rolls_back_and_retry')),
    "test_customer_update_postgres": (5, ('test_pg_patch_fields_permissions_and_audit', 'test_pg_precommit_failure_rolls_back_and_retry', 'test_pg_concurrent_distinct_customers_allow_same_name_and_chain')),
    "test_supplier_create_postgres": (7, ('test_pg_route_saves_all_fields_and_audit_same_session', 'test_pg_route_refuses_unauthenticated_and_forbidden_without_writes', 'test_pg_route_failure_rolls_back_then_retry', 'test_pg_concurrent_suppliers_keep_audit_chain', 'test_pg_create_preserves_raw_fields_duplicates_and_validation')),
    "test_brand_update_postgres": (3, ('test_pg_update_persistence_omission_null_and_chain', 'test_pg_duplicate_and_audit_finalize_failure_roll_back_then_retry', 'test_pg_case_variant_update_is_allowed')),
    "test_customer_create_postgres": (6, ("test_pg_route_saves_all_fields_and_audit_same_session", "test_pg_route_refuses_unauthenticated_and_forbidden_without_writes", "test_pg_route_failure_rolls_back_then_retry", "test_pg_concurrent_customers_keep_audit_chain")),
    "test_brand_create_postgres": (2, ("test_pg_create_duplicate_and_audit", "test_pg_audit_failure_rolls_back_then_retry")),
    "test_planning_alternate_creation_postgres": (5, ()),
    "test_purchase_conversion_postgres": (7, ()),
    "test_bom_add_characterization": (54, ()),
    "test_forecast_review_postgres": (9, ()),
    "test_stock_movement_and_reservation_postgres": (7, ()),
    "test_sales_update_old_behavior": (4, (
        "test_pg_stale_unchanged_status_cannot_rewind_concurrent_workflow",
        "test_pg_edit_and_audit_rollback_together_then_retry",
        "test_pg_unknown_customer_fails_fk_atomically_without_custom_service_refusal",
    )),
    "test_finance_sales_invoice_generation": (5, (
        "test_sales_generation_pg_failure_rolls_back_invoice_and_audit_then_retry",
        "test_sales_generation_pg_serializes_two_issuers_of_one_order",
        "test_sales_generation_pg_and_manual_entry_points_share_one_invoice",
    )),
    "test_invoice_creation_integrity": (4, (
        "test_concurrent_same_entry_point_creates_exactly_one_invoice",
        "test_concurrent_mixed_entry_points_create_exactly_one_invoice",
        "test_concurrent_creation_does_not_duplicate_invoice_numbers",
    )),
    "test_customer_invoice_creation_race": (10, ()),
    "test_shipment_reopen_invoice_postgres": (4, (
        "test_pg_shipment_reopen_finance_participant_same_session_and_no_early_commit",
        "test_pg_shipment_reopen_preflights_every_invoice_before_any_finance_write",
        "test_pg_shipment_reopen_audit_failure_rolls_back_and_retry_commits_all",
        "test_pg_invoice_payment_and_shipment_reopen_serialize_on_invoice_row",
    )),
    "test_purchase_receipt_concurrency": (2, ("test_postgres_receipts_serialize_line_totals_and_closed_order_no_write",)),
    "test_purchase_receipt_idempotency": (3, ("test_postgres_concurrent_receipts_serialize_before_replay", "test_postgres_receipt_audit_finalization_failure_rolls_back_then_replays")),
    "test_item_delete_postgres": (12, (
        "test_pg_delete_and_archive_share_session_and_preserve_audit",
        "test_pg_actual_audit_finalization_failure_rolls_back",
        "test_pg_unchecked_direct_reference_rejects_delete_atomically",
        "test_pg_item_lock_serializes_reference_insert_and_audit",
    )),
    "test_process_qr_size_setup_postgres": (7, (
        "test_postgres_setup_audit_failure_rolls_back",
        "test_postgres_simultaneous_setup_serializes",
        "test_postgres_setup_then_generic_writer_waits_on_parent_fk",
        "test_postgres_http_failure_teardown_rolls_back",
        "test_postgres_deferred_commit_failure_rolls_back_request",
    )),
    "test_model_image_delete_postgres": (5, (
        "test_pg_denied_usluga_and_reverse_scope_keep_binary",
        "test_pg_request_failure_rolls_back_binary_and_audit",
        "test_pg_update_then_delete_waits_and_audits_loaded_url",
        "test_pg_deferred_delete_commit_failure_rolls_back_binary_and_audit",
    )),
    "test_modelsize_create_postgres": (2, ("test_pg_create_atomic_audit_and_failure_retry", "test_pg_concurrent_duplicate_creates")),
    "test_modelcolor_create_postgres": (27, ()),
}
REQUIRED_CASES = json.loads(
    Path(__file__).with_name("refactor_pg_required_cases.json").read_text(encoding="utf-8")
)["cases"]


def required_nodes() -> list[str]:
    result = []
    for module, (_, names) in GROUPS.items():
        path = f"app/tests/{module}.py"
        if names:
            result.extend(f"{path}::{name}" for name in names)
        else:
            result.append(path)
    return result


def check_report(report: Path) -> dict[str, int]:
    return check_required_report(report, GROUPS, REQUIRED_CASES)


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

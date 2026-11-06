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
import xml.etree.ElementTree as ET


# Minimum collected counts pin the current parameterized business cases. Adding
# cases is allowed; removing a required case needs an explicit ledger change.
GROUPS = {
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

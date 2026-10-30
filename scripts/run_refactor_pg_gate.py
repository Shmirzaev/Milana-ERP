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
 'test_planning_alternate_creation_postgres': (5, ()),
 'test_purchase_conversion_postgres': (7, ()),
 'test_bom_add_characterization': (54, ()),
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
 'test_model_paid_operations_postgres': (10,
                                         ('test_pg_paid_operations_patch_round_trips_typed_rows_and_openapi',
                                          'test_pg_paid_operations_invalid_and_cross_factory_patch_leave_family_and_audit_unchanged',
                                          'test_pg_paid_operations_scoped_save_keeps_other_factory_opaque_legacy_and_other_family',
                                          'test_pg_usluga_paid_operation_routes_apply_eco_factory_and_typed_sections',
                                          'test_pg_model_create_keeps_historical_paid_operation_json_opaque',
                                          'test_pg_paid_operations_failure_rolls_back_then_same_session_retry',
                                          'test_pg_paid_operations_concurrent_factories_serialize_same_family_and_prove_row_lock_wait')),
 'test_direct_finished_goods_reserve_postgres': (6,
                                                 ('test_pg_direct_reserve_manual_package_persists_rows_and_audit',
                                                  'test_pg_direct_reserve_denied_actor_makes_no_business_writes',
                                                  'test_pg_direct_reserve_competing_piece_requests_do_not_oversell',
                                                  'test_pg_direct_reserve_failure_rolls_back_then_retry'))}
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

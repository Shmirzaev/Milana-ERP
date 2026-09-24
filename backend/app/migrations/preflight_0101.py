"""Read-only preview of payroll factory attribution in Alembic revision 0101.

This report is an operator-review aid, not a migration approval or safety
claim. It mirrors the declared UPDATE/constraint predicates in
``0101_payroll_factory_scope.py`` only at its exact declared predecessor.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy import MetaData, Table
from sqlalchemy.engine import Connection, Engine


REVISION_0101 = "0101_payroll_factory_scope"
PREDECESSOR_0101 = "0100_material_roll_weights"
VALID_FACTORY_CODES = {"MIL", "BST", "ECO"}
_FACTORY_TABLES = (
    "employees",
    "payroll_periods",
    "payroll_records",
    "payroll_qr_labels",
    "payroll_adjustments",
)


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rows(connection: Connection, table: Table, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(
        sa.select(*(table.c[name] for name in columns)).order_by(table.c.id)
    ).mappings().all()]


def _reflect(connection: Connection, table_name: str) -> Table:
    return Table(table_name, MetaData(), autoload_with=connection)


def _id_list(rows: list[dict[str, Any]]) -> list[Any]:
    return [row["id"] for row in rows]


def _ids_hash(ids: list[Any]) -> str:
    return _hash(ids)


def _prediction_summary(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    code_counts = Counter(row["factory_code_after"] for row in predictions)
    ids = [row["id"] for row in predictions]
    return {
        "count": len(predictions),
        "ids": ids,
        "factory_code_after_counts": dict(sorted(code_counts.items())),
        "predictions": predictions,
        "snapshot_sha256": _hash(predictions),
    }


def _duplicate_groups(
    predictions: list[dict[str, Any]], source_rows: list[dict[str, Any]], key_column: str,
) -> list[dict[str, Any]]:
    by_id = {row["id"]: row for row in source_rows}
    grouped: dict[tuple[Any, Any], list[Any]] = defaultdict(list)
    for prediction in predictions:
        value = by_id[prediction["id"]][key_column]
        # PostgreSQL and SQLite unique constraints allow multiple NULL values.
        if value is None:
            continue
        if not isinstance(value, (str, int, float, bytes)):
            raise TypeError(f"Unsupported unique-key value type in {key_column}")
        grouped[(prediction["factory_code_after"], value)].append(prediction["id"])
    duplicate_groups = []
    for (factory_code, _), ids in grouped.items():
        if len(ids) > 1:
            ordered_ids = sorted(ids)
            duplicate_groups.append({
                "factory_code": factory_code,
                "count": len(ordered_ids),
                "ids": ordered_ids,
                "ids_sha256": _ids_hash(ordered_ids),
            })
    return sorted(duplicate_groups, key=lambda group: (group["factory_code"], group["ids"]))


def _predecessor_mismatch(revisions: list[str]) -> dict[str, Any]:
    return {
        "revision": REVISION_0101,
        "expected_predecessor": PREDECESSOR_0101,
        "database_revisions": revisions,
        "migration_pending": revisions == [PREDECESSOR_0101],
        "applicability": "revision_mismatch_review_required",
        "affected_rows_inspected": False,
        "blockers": ["Database revision is not exactly 0100_material_roll_weights."],
        "limitations": "No business tables were inspected because the exact predecessor check failed.",
    }


def preview_0101(connection: Connection) -> dict[str, Any]:
    """Project revision 0101's factory values and collision/blocker sets."""
    try:
        versions = Table("alembic_version", MetaData(), autoload_with=connection)
        revisions = sorted(connection.execute(
            sa.select(versions.c.version_num).order_by(versions.c.version_num)
        ).scalars().all())
    except sa.exc.SQLAlchemyError:
        return _predecessor_mismatch([])

    if revisions != [PREDECESSOR_0101]:
        return _predecessor_mismatch(revisions)

    try:
        tables = {name: _reflect(connection, name) for name in _FACTORY_TABLES}
        users = _reflect(connection, "users")
        departments = _reflect(connection, "departments")
        sewing_flows = _reflect(connection, "sewing_flows")
        bundles = _reflect(connection, "bundles")

        employees = _rows(connection, tables["employees"], ("id", "user_id", "department_id", "employee_no"))
        periods = _rows(connection, tables["payroll_periods"], ("id", "period_no", "created_by"))
        records = _rows(connection, tables["payroll_records"], (
            "id", "payroll_period_id", "employee_id", "scanned_by", "scan_uid", "dedupe_key",
        ))
        labels = _rows(connection, tables["payroll_qr_labels"], (
            "id", "payroll_record_id", "sewing_flow_id", "production_order_id", "issued_by", "label_uid",
        ))
        adjustments = _rows(connection, tables["payroll_adjustments"], (
            "id", "employee_id", "created_by",
        ))
        user_rows = _rows(connection, users, ("id", "factory_code"))
        department_rows = _rows(connection, departments, ("id", "code"))
        flow_rows = _rows(connection, sewing_flows, ("id", "factory_code"))
        bundle_rows = _rows(connection, bundles, (
            "id", "production_order_id", "status", "sewing_factory_code",
        ))
    except (sa.exc.SQLAlchemyError, KeyError, TypeError) as exc:
        return {
            "revision": REVISION_0101,
            "expected_predecessor": PREDECESSOR_0101,
            "database_revisions": revisions,
            "migration_pending": True,
            "applicability": "predecessor_schema_review_required",
            "affected_rows_inspected": False,
            "blockers": [f"Predecessor schema does not support the declared projection ({type(exc).__name__})."],
            "limitations": "Business-row predictions were not produced because required columns/tables could not be inspected.",
        }

    user_code = {row["id"]: row["factory_code"] for row in user_rows}
    department_code = {row["id"]: row["code"] for row in department_rows}
    flow_code = {row["id"]: row["factory_code"] for row in flow_rows}
    employee_predictions: list[dict[str, Any]] = []
    employee_after: dict[Any, str] = {}
    for row in employees:
        code = user_code.get(row["user_id"])
        source = "employee_user"
        if code is None:
            department_id = row["department_id"]
            dept = department_code.get(department_id)
            if department_id in department_code:
                if dept in {"BST", "BPK"}:
                    code, source = "BST", "employee_department_mapping"
                elif dept in {"ECT", "ECO", "ECP"}:
                    code, source = "ECO", "employee_department_mapping"
                else:
                    code, source = "MIL", "employee_department_default_mil"
            else:
                code, source = "MIL", "employee_fallback_mil"
        employee_after[row["id"]] = code
        employee_predictions.append({"id": row["id"], "factory_code_after": code, "source": source})

    record_predictions = []
    record_after: dict[Any, str] = {}
    for row in records:
        code = employee_after.get(row["employee_id"])
        source = "record_employee"
        if code is None:
            code = user_code.get(row["scanned_by"])
            source = "record_scanned_by_user"
        if code is None:
            code, source = "MIL", "record_fallback_mil"
        record_after[row["id"]] = code
        record_predictions.append({"id": row["id"], "factory_code_after": code, "source": source})

    period_record_codes: dict[Any, list[tuple[Any, str]]] = defaultdict(list)
    for record in records:
        period_id = record["payroll_period_id"]
        if period_id is not None:
            period_record_codes[period_id].append((record["id"], record_after[record["id"]]))
    mixed_periods = []
    for period_id, recs in period_record_codes.items():
        codes = sorted({code for _, code in recs})
        if len(codes) > 1:
            rec_ids = sorted(record_id for record_id, _ in recs)
            mixed_periods.append({
                "payroll_period_id": period_id,
                "count": len(rec_ids),
                "payroll_record_ids": rec_ids,
                "factory_codes": codes,
                "records_sha256": _hash([
                    {"id": record_id, "factory_code_after": code}
                    for record_id, code in sorted(recs)
                ]),
            })

    period_predictions = []
    for row in periods:
        recs = period_record_codes.get(row["id"], [])
        if recs:
            code = min(value for _, value in recs)
            source = "period_minimum_payroll_record_factory"
        elif user_code.get(row["created_by"]) is not None:
            code = user_code[row["created_by"]]
            source = "period_creator_user"
        else:
            code, source = "MIL", "period_fallback_mil"
        period_predictions.append({"id": row["id"], "factory_code_after": code, "source": source})

    active_bundles: dict[Any, list[str]] = defaultdict(list)
    for row in bundle_rows:
        code = row["sewing_factory_code"]
        # SQL ``status <> 'cancelled'`` excludes NULL status values.
        if row["status"] is not None and row["status"] != "cancelled" and code is not None:
            active_bundles[row["production_order_id"]].append(code)
    label_predictions = []
    ambiguous_bundle_labels = []
    for row in labels:
        code = record_after.get(row["payroll_record_id"])
        source = "label_payroll_record"
        if code is None:
            code = flow_code.get(row["sewing_flow_id"])
            source = "label_sewing_flow"
        candidates = sorted(set(active_bundles.get(row["production_order_id"], [])))
        if code is None and len(candidates) == 1:
            code, source = candidates[0], "label_single_bundle_factory"
        elif code is None and len(candidates) > 1:
            ambiguous_bundle_labels.append({
                "id": row["id"],
                "production_order_id": row["production_order_id"],
                "candidate_factory_codes": candidates,
            })
        if code is None:
            code = user_code.get(row["issued_by"])
            source = "label_issuer_user"
        if code is None:
            code, source = "MIL", "label_fallback_mil"
        label_predictions.append({"id": row["id"], "factory_code_after": code, "source": source})

    adjustment_predictions = []
    for row in adjustments:
        code = employee_after.get(row["employee_id"])
        source = "adjustment_employee"
        if code is None:
            code = user_code.get(row["created_by"])
            source = "adjustment_creator_user"
        if code is None:
            code, source = "MIL", "adjustment_fallback_mil"
        adjustment_predictions.append({"id": row["id"], "factory_code_after": code, "source": source})

    predictions_by_table = {
        "employees": employee_predictions,
        "payroll_periods": period_predictions,
        "payroll_records": record_predictions,
        "payroll_qr_labels": label_predictions,
        "payroll_adjustments": adjustment_predictions,
    }
    source_rows_by_table = {
        "employees": employees,
        "payroll_periods": periods,
        "payroll_records": records,
        "payroll_qr_labels": labels,
        "payroll_adjustments": adjustments,
    }
    unique_keys = {
        "employees": ("employee_no",),
        "payroll_periods": ("period_no",),
        "payroll_records": ("scan_uid", "dedupe_key"),
        "payroll_qr_labels": ("label_uid",),
        "payroll_adjustments": (),
    }
    unique_collisions: dict[str, Any] = {}
    for table_name, keys in unique_keys.items():
        unique_collisions[table_name] = {
            key: {
                "constraint": {
                    "employee_no": "uq_employees_factory_employee_no",
                    "period_no": "uq_payroll_periods_factory_period_no",
                    "scan_uid": "uq_payroll_records_factory_scan_uid",
                    "dedupe_key": "uq_payroll_records_factory_dedupe_key",
                    "label_uid": "uq_payroll_qr_labels_factory_label_uid",
                }[key],
                "groups": _duplicate_groups(
                    predictions_by_table[table_name], source_rows_by_table[table_name], key,
                ),
            }
            for key in keys
        }

    invalid_codes = {}
    default_to_mil = {}
    for table_name, predictions in predictions_by_table.items():
        invalid = [row for row in predictions if row["factory_code_after"] not in VALID_FACTORY_CODES]
        invalid_codes[table_name] = {
            "count": len(invalid),
            "ids": _id_list(invalid),
            "codes": sorted({str(row["factory_code_after"]) for row in invalid}),
            "ids_sha256": _ids_hash(_id_list(invalid)),
            "snapshot_sha256": _hash([
                {"id": row["id"], "factory_code_after": row["factory_code_after"]}
                for row in invalid
            ]),
        }
        fallback = [row for row in predictions if row["source"].endswith("fallback_mil")
                    or row["source"].endswith("department_default_mil")]
        default_to_mil[table_name] = {
            "count": len(fallback),
            "ids": _id_list(fallback),
            "ids_sha256": _ids_hash(_id_list(fallback)),
            "snapshot_sha256": _hash([
                {"id": row["id"], "source": row["source"]} for row in fallback
            ]),
        }

    blockers = []
    if mixed_periods:
        blockers.append("One or more payroll periods contain projected records from multiple factories; 0101 raises and aborts.")
    if any(entry["count"] for entry in invalid_codes.values()):
        blockers.append("One or more projected factory codes fail 0101's MIL/BST/ECO check constraints.")
    if any(group["groups"] for table in unique_collisions.values() for group in table.values()):
        blockers.append("One or more projected factory-scoped unique keys collide.")
    if ambiguous_bundle_labels:
        blockers.append("Some labels have multiple active bundle factory candidates and fall through to later attribution sources.")
    if any(entry["count"] for entry in default_to_mil.values()):
        blockers.append("Some rows receive MIL solely through a migration fallback or department default.")

    return {
        "revision": REVISION_0101,
        "expected_predecessor": PREDECESSOR_0101,
        "database_revisions": revisions,
        "migration_pending": True,
        "applicability": "operator_review_required" if not blockers else "blockers_found_review_required",
        "affected_rows_inspected": True,
        "factory_code_predictions": {
            table_name: _prediction_summary(predictions)
            for table_name, predictions in predictions_by_table.items()
        },
        "invalid_factory_codes": invalid_codes,
        "default_to_mil": default_to_mil,
        "mixed_payroll_periods": {
            "count": len(mixed_periods),
            "periods": mixed_periods,
            "snapshot_sha256": _hash(mixed_periods),
        },
        "duplicate_new_unique_keys": unique_collisions,
        "ambiguous_bundle_factory_attribution": {
            "count": len(ambiguous_bundle_labels),
            "labels": ambiguous_bundle_labels,
            "snapshot_sha256": _hash(ambiguous_bundle_labels),
        },
        "blockers": blockers,
        "limitations": (
            "This is a read-only prediction of the declared 0101 SQL predicates and new unique keys at the exact predecessor. "
            "It does not execute or approve the migration, verify recovery backups, inspect undeclared references, or establish "
            "business correctness of factory attribution. IDs and factory codes are included for operator review; names, "
            "payroll amounts, employee numbers, scan UIDs, dedupe keys and label UIDs are omitted. Hashes identify reported "
            "IDs/predictions and are not backups. An empty blocker set is not evidence that the migration is safe."
        ),
    }


def read_only_preflight_0101(engine: Engine) -> dict[str, Any]:
    """Run the preview in one read-only transaction on PostgreSQL or SQLite."""
    if engine.dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError(f"Unsupported database dialect: {engine.dialect.name}")
    with engine.connect() as connection:
        with connection.begin():
            if connection.dialect.name == "postgresql":
                connection.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                return preview_0101(connection)
            previous_query_only = int(connection.exec_driver_sql("PRAGMA query_only").scalar_one())
            if not previous_query_only:
                connection.exec_driver_sql("PRAGMA query_only = ON")
            try:
                return preview_0101(connection)
            finally:
                if not previous_query_only:
                    connection.exec_driver_sql("PRAGMA query_only = OFF")

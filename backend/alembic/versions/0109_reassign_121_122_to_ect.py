"""Route production orders 121 and 122 to Eco Cotton Cutting.

Revision ID: 0109_reassign_121_122_ect
Revises: 0108_usluga_report_pieces
Create Date: 2026-08-26
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
from alembic import op


revision = "0109_reassign_121_122_ect"
down_revision = "0108_usluga_report_pieces"
branch_labels = None
depends_on = None


TARGET_PRODUCTION_NUMBERS = ("PO-2026-000121", "PO-2026-000122")
SOURCE_DEPARTMENT_CODE = "CUT"
TARGET_DEPARTMENT_CODE = "ECT"


def _unsafe_reason(row: Mapping[str, Any]) -> str | None:
    if row["production_type"] != "branded_stock":
        return f"unexpected production type {row['production_type']!r}"
    if row["production_status"] != "planning":
        return f"production status is {row['production_status']!r}, not 'planning'"
    if row["operation"] != "cutting":
        return f"work order operation is {row['operation']!r}, not 'cutting'"
    if row["department_code"] != SOURCE_DEPARTMENT_CODE:
        return f"cutting department is {row['department_code']!r}, not {SOURCE_DEPARTMENT_CODE!r}"
    if row["work_status"] != "waiting":
        return f"cutting work order status is {row['work_status']!r}, not 'waiting'"
    if row["start_time"] is not None or row["end_time"] is not None:
        return "cutting work order has start/end timestamps"

    quantity_fields = (
        "actual_input_qty",
        "actual_output_qty",
        "passed_qty",
        "failed_qty",
        "rework_qty",
    )
    changed_quantities = {
        field: int(row[field] or 0)
        for field in quantity_fields
        if int(row[field] or 0) != 0
    }
    if changed_quantities:
        return f"cutting work order has recorded quantities {changed_quantities}"

    evidence_fields = (
        "production_batch_count",
        "cutting_record_count",
        "bundle_count",
        "sewing_record_count",
        "packaging_record_count",
        "package_count",
        "sewing_assignment_count",
        "replacement_request_count",
    )
    evidence = {
        field: int(row[field] or 0)
        for field in evidence_fields
        if int(row[field] or 0) != 0
    }
    if evidence:
        return f"production evidence already exists {evidence}"
    return None


def _entry_hash(
    *,
    previous: str | None,
    entity_id: int,
    old_value: dict[str, Any],
    new_value: dict[str, Any],
) -> str:
    payload = {
        "prev_hash": previous,
        "user_id": None,
        "action": "reassign_cutting_department",
        "entity_type": "WorkOrder",
        "entity_id": entity_id,
        "old_value": old_value,
        "new_value": new_value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _target_rows(connection: sa.Connection) -> list[Mapping[str, Any]]:
    return list(
        connection.execute(
            sa.text(
                """
                SELECT
                    po.id AS production_order_id,
                    po.production_no,
                    po.production_type,
                    po.status AS production_status,
                    wo.id AS work_order_id,
                    wo.operation,
                    wo.status AS work_status,
                    wo.department_id,
                    d.code AS department_code,
                    wo.actual_input_qty,
                    wo.actual_output_qty,
                    wo.passed_qty,
                    wo.failed_qty,
                    wo.rework_qty,
                    wo.start_time,
                    wo.end_time,
                    (SELECT COUNT(*) FROM production_batches pb
                     WHERE pb.production_order_id = po.id) AS production_batch_count,
                    (SELECT COUNT(*) FROM cutting_records cr
                     WHERE cr.work_order_id = wo.id) AS cutting_record_count,
                    (SELECT COUNT(*) FROM bundles b
                     WHERE b.production_order_id = po.id) AS bundle_count,
                    (SELECT COUNT(*) FROM sewing_records sr
                     JOIN work_orders srwo ON srwo.id = sr.work_order_id
                     WHERE srwo.production_order_id = po.id) AS sewing_record_count,
                    (SELECT COUNT(*) FROM packaging_records pr
                     JOIN work_orders prwo ON prwo.id = pr.work_order_id
                     WHERE prwo.production_order_id = po.id) AS packaging_record_count,
                    (SELECT COUNT(*) FROM packages p
                     WHERE p.production_order_id = po.id) AS package_count,
                    (SELECT COUNT(*) FROM sewing_assignments sassign
                     JOIN work_orders sawo ON sawo.id = sassign.work_order_id
                     WHERE sawo.production_order_id = po.id) AS sewing_assignment_count,
                    (SELECT COUNT(*) FROM sewing_replacement_requests srr
                     WHERE srr.production_order_id = po.id) AS replacement_request_count
                FROM production_orders po
                JOIN work_orders wo
                  ON wo.production_order_id = po.id
                 AND wo.operation = 'cutting'
                JOIN departments d ON d.id = wo.department_id
                WHERE po.production_no IN :production_numbers
                ORDER BY po.production_no, wo.id
                FOR UPDATE OF po, wo
                """
            ).bindparams(sa.bindparam("production_numbers", expanding=True)),
            {"production_numbers": TARGET_PRODUCTION_NUMBERS},
        ).mappings()
    )


def upgrade() -> None:
    connection = op.get_bind()
    rows = _target_rows(connection)
    if not rows:
        return

    found_numbers = [str(row["production_no"]) for row in rows]
    if set(found_numbers) != set(TARGET_PRODUCTION_NUMBERS):
        missing = sorted(set(TARGET_PRODUCTION_NUMBERS) - set(found_numbers))
        raise RuntimeError(f"Target production orders are missing cutting work orders: {missing}")
    if len(found_numbers) != len(set(found_numbers)):
        raise RuntimeError(f"Duplicate cutting work orders found for targets: {found_numbers}")

    ect_department_id = connection.execute(
        sa.text("SELECT id FROM departments WHERE code = :code"),
        {"code": TARGET_DEPARTMENT_CODE},
    ).scalar_one_or_none()
    if ect_department_id is None:
        raise RuntimeError("Eco Cotton Cutting department ECT is not configured")

    for row in rows:
        reason = _unsafe_reason(row)
        if reason:
            raise RuntimeError(f"Refusing to reassign {row['production_no']}: {reason}")

    # Serialize the correction with application audit writes so every inserted
    # audit row links to the latest hash while the assignment changes atomically.
    connection.execute(sa.text("LOCK TABLE audit_logs IN SHARE ROW EXCLUSIVE MODE"))
    previous_hash = connection.execute(
        sa.text("SELECT entry_hash FROM audit_logs WHERE entry_hash IS NOT NULL ORDER BY id DESC LIMIT 1")
    ).scalar_one_or_none()

    for row in rows:
        work_order_id = int(row["work_order_id"])
        production_order_id = int(row["production_order_id"])
        production_no = str(row["production_no"])
        result = connection.execute(
            sa.text(
                """
                UPDATE work_orders
                   SET department_id = :department_id,
                       updated_at = NOW()
                 WHERE id = :work_order_id
                   AND department_id = :old_department_id
                   AND operation = 'cutting'
                   AND status = 'waiting'
                """
            ),
            {
                "department_id": int(ect_department_id),
                "work_order_id": work_order_id,
                "old_department_id": int(row["department_id"]),
            },
        )
        if result.rowcount != 1:
            raise RuntimeError(f"Concurrent change prevented reassignment of {production_no}")

        old_value = {
            "production_order_id": production_order_id,
            "production_no": production_no,
            "operation": "cutting",
            "department_code": SOURCE_DEPARTMENT_CODE,
            "status": "waiting",
        }
        new_value = {
            "production_order_id": production_order_id,
            "production_no": production_no,
            "operation": "cutting",
            "department_code": TARGET_DEPARTMENT_CODE,
            "status": "waiting",
            "reason": "User requested these untouched jobs be routed to Eco Cotton Cutting",
        }
        entry_hash = _entry_hash(
            previous=previous_hash,
            entity_id=work_order_id,
            old_value=old_value,
            new_value=new_value,
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO audit_logs
                    (user_id, action, entity_type, entity_id,
                     old_value_json, new_value_json, prev_hash, entry_hash)
                VALUES
                    (NULL, 'reassign_cutting_department', 'WorkOrder', :entity_id,
                     CAST(:old_value AS json), CAST(:new_value AS json), :prev_hash, :entry_hash)
                """
            ),
            {
                "entity_id": work_order_id,
                "old_value": json.dumps(old_value, separators=(",", ":")),
                "new_value": json.dumps(new_value, separators=(",", ":")),
                "prev_hash": previous_hash,
                "entry_hash": entry_hash,
            },
        )
        previous_hash = entry_hash

    verified = dict(
        connection.execute(
            sa.text(
                """
                SELECT po.production_no, d.code
                  FROM production_orders po
                  JOIN work_orders wo
                    ON wo.production_order_id = po.id
                   AND wo.operation = 'cutting'
                  JOIN departments d ON d.id = wo.department_id
                 WHERE po.production_no IN :production_numbers
                """
            ).bindparams(sa.bindparam("production_numbers", expanding=True)),
            {"production_numbers": found_numbers},
        ).all()
    )
    wrong = {number: code for number, code in verified.items() if code != TARGET_DEPARTMENT_CODE}
    if len(verified) != len(found_numbers) or wrong:
        raise RuntimeError(f"Cutting reassignment verification failed: {verified}")


def downgrade() -> None:
    # The previous CUT assignment was an operational mistake. Do not route the
    # jobs back there during an application rollback.
    pass

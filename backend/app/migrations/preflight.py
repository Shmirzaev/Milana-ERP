"""Read-only previews for data-affecting Alembic revisions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import sqlalchemy as sa


REVISION_0130 = "0130_eco_fabric_transfers"
PREDECESSOR_0130 = "0129_user_access_policy"
TARGET_PERMISSION_0130 = "inventory.eco_transfers"
TARGET_EMAIL_0130 = "mubina@milanapremium.uz"
REVISION_0055 = "0055_delete_mistaken_po15"
PREDECESSOR_0055 = "0054_payroll_qr_ids"
TARGET_PRODUCTION_NO_0055 = "PO-2026-000015"
_DIRECT_CHILD_FKS_0055 = {
    ("work_orders", "production_order_id"),
    ("production_order_items", "production_order_id"),
}
_WORK_ORDER_ACTIVITY_FIELDS_0055 = (
    "actual_input_qty", "actual_output_qty", "passed_qty", "failed_qty", "rework_qty",
)


def _snapshot_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preview_0055_deletion(connection: sa.Connection) -> dict[str, Any]:
    """Preview revision 0055's exact direct deletes and linked-row risks.

    This does not authorize deletion. Row hashes identify the reviewed data;
    recovery still requires a verified database backup because 0055 has no
    reconstructive downgrade.
    """
    metadata = sa.MetaData()
    tables = {
        name: sa.Table(name, metadata, autoload_with=connection)
        for name in ("production_orders", "work_orders", "production_order_items")
    }
    orders = tables["production_orders"]
    target_rows = connection.execute(
        sa.select(orders).where(orders.c.production_no == TARGET_PRODUCTION_NO_0055)
        .order_by(orders.c.id)
    ).mappings().all()
    target_ids = [int(row["id"]) for row in target_rows]
    direct_rows: dict[str, list[dict[str, Any]]] = {"production_orders": [dict(row) for row in target_rows]}
    for name in ("work_orders", "production_order_items"):
        table = tables[name]
        direct_rows[name] = (
            [dict(row) for row in connection.execute(
                sa.select(table).where(table.c.production_order_id.in_(target_ids))
                .order_by(table.c.id)
            ).mappings()]
            if target_ids else []
        )

    guarded_work_order_ids = []
    null_guard_work_order_ids = []
    for row in direct_rows["work_orders"]:
        values = [row["status"], *(row[field] for field in _WORK_ORDER_ACTIVITY_FIELDS_0055)]
        if any(value is None for value in values):
            null_guard_work_order_ids.append(int(row["id"]))
        if (row["status"] is not None and row["status"] != "waiting") or any(
            row[field] is not None and row[field] != 0
            for field in _WORK_ORDER_ACTIVITY_FIELDS_0055
        ):
            guarded_work_order_ids.append(int(row["id"]))

    ids_by_table = {
        name: [int(row["id"]) for row in rows]
        for name, rows in direct_rows.items()
    }
    references = []
    unsupported_references = []
    inspector = sa.inspect(connection)
    for table_name in inspector.get_table_names():
        for fk in inspector.get_foreign_keys(table_name):
            parent = fk.get("referred_table")
            if parent not in ids_by_table or not ids_by_table[parent]:
                continue
            columns = fk.get("constrained_columns") or []
            parent_columns = fk.get("referred_columns") or []
            if len(columns) != 1 or parent_columns != ["id"]:
                unsupported_references.append({"table": table_name, "constraint": fk.get("name")})
                continue
            column = columns[0]
            if (table_name, column) in _DIRECT_CHILD_FKS_0055 and parent == "production_orders":
                continue
            table = sa.Table(table_name, metadata, autoload_with=connection)
            count = connection.execute(
                sa.select(sa.func.count()).select_from(table)
                .where(table.c[column].in_(ids_by_table[parent]))
            ).scalar_one()
            if count:
                references.append({
                    "table": table_name,
                    "column": column,
                    "referred_table": parent,
                    "count": int(count),
                    "ondelete": (fk.get("options") or {}).get("ondelete"),
                })

    return {
        "revision": REVISION_0055,
        "expected_predecessor": PREDECESSOR_0055,
        "production_no": TARGET_PRODUCTION_NO_0055,
        "matching_order_count": len(target_rows),
        "direct_deletes": {
            name: {
                "count": len(rows),
                "ids": ids_by_table[name],
                "snapshot_sha256": _snapshot_hash({"rows": rows}),
            }
            for name, rows in direct_rows.items()
        },
        "migration_guard_work_order_ids": guarded_work_order_ids,
        "null_guard_work_order_ids": null_guard_work_order_ids,
        "external_references": references,
        "uninspected_composite_references": unsupported_references,
        "limitations": "Reference counts cover declared foreign keys only; review application-level references and a verified backup before approving deletion.",
        "recovery": "Take and verify a database backup before approval; revision 0055 deletes rows and its downgrade cannot restore them.",
    }


def read_only_preflight_0055(engine: sa.Engine) -> dict[str, Any]:
    """Run the 0055 deletion preview in a consistent read-only transaction."""
    with engine.connect() as connection:
        with connection.begin():
            if connection.dialect.name == "postgresql":
                connection.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            current = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            report = preview_0055_deletion(connection)
            report["database_revision"] = current
            report["migration_pending"] = current == PREDECESSOR_0055
            if current != PREDECESSOR_0055:
                report["applicability"] = (
                    "migration_already_applied" if current == REVISION_0055
                    else "revision_mismatch_review_required"
                )
            elif report["matching_order_count"] == 0:
                report["applicability"] = "no_target"
            elif (
                report["matching_order_count"] != 1
                or report["migration_guard_work_order_ids"]
                or report["null_guard_work_order_ids"]
                or report["external_references"]
                or report["uninspected_composite_references"]
            ):
                report["applicability"] = "manual_review_required"
            else:
                report["applicability"] = "ready_for_operator_review"
            return report


def preview_0130_permissions(connection: sa.Connection) -> dict[str, Any]:
    """Return exact current and post-upgrade grants for 0130's target account.

    The result deliberately omits the email address. The ``before`` object is
    sufficient to restore the two fields if an operator approves a correction.
    """
    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("email", sa.String),
        sa.column("extra_permissions", sa.JSON),
        sa.column("access_policy", sa.JSON),
    )
    rows = connection.execute(
        sa.select(users.c.id, users.c.extra_permissions, users.c.access_policy)
        .where(sa.func.lower(users.c.email) == TARGET_EMAIL_0130)
        .order_by(users.c.id)
    ).mappings()

    previews = []
    for row in rows:
        before = {
            "extra_permissions": row["extra_permissions"],
            "access_policy": row["access_policy"],
        }
        try:
            # Keep the conversion semantics aligned with revision 0130. If an
            # existing value is malformed, the migration would fail; report
            # that fact instead of presenting a fabricated successful preview.
            after_grants = list(dict.fromkeys([
                *(list(before["extra_permissions"] or [])),
                TARGET_PERMISSION_0130,
            ]))
            after_policy = dict(before["access_policy"] or {})
            if "MIL" in after_policy:
                mil = dict(after_policy["MIL"])
                mil["allow"] = list(dict.fromkeys([*(mil.get("allow", [])), TARGET_PERMISSION_0130]))
                mil["deny"] = [permission for permission in mil.get("deny", [])
                               if permission != TARGET_PERMISSION_0130]
                after_policy["MIL"] = mil
        except (TypeError, ValueError) as exc:
            previews.append({
                "user_id": int(row["id"]),
                "before": before,
                "changed": None,
                "blocker": f"Revision 0130 would fail converting existing permission data: {type(exc).__name__}",
                "before_sha256": _snapshot_hash(before),
            })
            continue
        after = {
            "extra_permissions": after_grants,
            "access_policy": after_policy or None,
        }
        previews.append({
            "user_id": int(row["id"]),
            "before": before,
            "after": after,
            "changed": before != after,
            "before_sha256": _snapshot_hash(before),
            "after_sha256": _snapshot_hash(after),
        })

    return {
        "revision": REVISION_0130,
        "expected_predecessor": PREDECESSOR_0130,
        "permission": TARGET_PERMISSION_0130,
        "matching_account_count": len(previews),
        "changed_account_count": sum(preview["changed"] is True for preview in previews),
        "blocked_account_count": sum("blocker" in preview for preview in previews),
        "accounts": previews,
        "recovery": "Each before object contains the exact extra_permissions and access_policy values to restore; hashes identify the reviewed snapshots.",
    }


def read_only_preflight_0130(engine: sa.Engine) -> dict[str, Any]:
    """Run the 0130 permission preview inside a read-only transaction."""
    with engine.connect() as connection:
        with connection.begin():
            if connection.dialect.name == "postgresql":
                connection.execute(sa.text("SET TRANSACTION READ ONLY"))
            current = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            report = preview_0130_permissions(connection)
            report["database_revision"] = current
            report["migration_pending"] = current == PREDECESSOR_0130
            report["applicability"] = (
                "blocked_by_migration_input" if current == PREDECESSOR_0130 and report["blocked_account_count"]
                else "ready_for_review" if current == PREDECESSOR_0130
                else "migration_already_applied" if current == REVISION_0130
                else "revision_mismatch_review_required"
            )
            return report

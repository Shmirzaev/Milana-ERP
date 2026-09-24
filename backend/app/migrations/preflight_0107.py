"""Read-only recovery snapshots for Usluga migration 0107.

This module previews the data operations in ``0107_usluga_cutting_approval``.
It never runs migration SQL and only produces a preview while exactly the
declared predecessor is installed.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

import sqlalchemy as sa


REVISION_0107 = "0107_usluga_cutting_approval"
PREDECESSOR_0107 = "0106_usluga_manual_fabric"
TARGET_PERMISSION_0107 = "usluga.cutting.approve"


def _snapshot_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pg_btrim(value: str | None) -> str | None:
    """Match PostgreSQL btrim(text)'s default ASCII-space trimming."""
    return value.strip(" ") if value is not None else None


def _derived_material_name(item: sa.RowMapping) -> str:
    name = _pg_btrim(item["item_name"])
    sku = _pg_btrim(item["item_sku"])
    return name or sku or f"Fabric #{item['item_id']}"


def _jsonb_append_permission(value: Any) -> Any:
    """Mirror 0107's JSONB ``?`` and ``|| [permission]`` for JSON values."""
    if value is None:
        return None
    if isinstance(value, dict) and TARGET_PERMISSION_0107 in value:
        return value
    if isinstance(value, list) and TARGET_PERMISSION_0107 in value:
        return value
    if isinstance(value, list):
        return [*value, TARGET_PERMISSION_0107]
    # PostgreSQL JSONB concatenation promotes a non-array operand to an array.
    return [value, TARGET_PERMISSION_0107]


def _not_applicable(current_revisions: list[str]) -> dict[str, Any]:
    return {
        "revision": REVISION_0107,
        "expected_predecessor": PREDECESSOR_0107,
        "database_revisions": current_revisions,
        "migration_pending": False,
        "applicability": "revision_mismatch_review_required",
        "affected_rows_inspected": False,
        "limitations": "The preview requires exactly the predecessor revision; no row-level conclusions were made.",
    }


def preview_0107(connection: sa.Connection) -> dict[str, Any]:
    """Return exact row identities and recovery snapshots without writing."""
    version_table = sa.Table("alembic_version", sa.MetaData(), autoload_with=connection)
    current_revisions = [
        str(row[0]) for row in connection.execute(
            sa.select(version_table.c.version_num).order_by(version_table.c.version_num)
        )
    ]
    if current_revisions != [PREDECESSOR_0107]:
        return _not_applicable(current_revisions)

    metadata = sa.MetaData()
    bom = sa.Table("model_bom", metadata, autoload_with=connection)
    models = sa.Table("models", metadata, autoload_with=connection)
    items = sa.Table("items", metadata, autoload_with=connection)
    bundles = sa.Table("bundles", metadata, autoload_with=connection)
    work_orders = sa.Table("work_orders", metadata, autoload_with=connection)
    cutting_records = sa.Table("cutting_records", metadata, autoload_with=connection)
    roles = sa.Table("roles", metadata, autoload_with=connection)

    # This is the exact 0107 predicate. Keep only columns that are changed or
    # needed to reconstruct the removed inventory links; omit notes and PII.
    fabric_rows = connection.execute(
        sa.select(
            bom.c.id.label("bom_id"), bom.c.model_id, bom.c.item_id,
            bom.c.stock_batch_id, bom.c.material_name,
            items.c.id.label("item_id"), items.c.name.label("item_name"),
            items.c.sku.label("item_sku"), items.c.category.label("item_category"),
        )
        .select_from(bom.join(models, bom.c.model_id == models.c.id).join(items, bom.c.item_id == items.c.id))
        .where(
            models.c.catalog_scope == "usluga",
            sa.func.lower(sa.func.coalesce(items.c.category, "")).in_(("fabric", "semi_finished")),
        )
        .order_by(bom.c.id)
    ).mappings().all()

    transformed_names: dict[int, str] = {}
    recovery_rows = []
    for row in fabric_rows:
        bom_id = int(row["bom_id"])
        derived_name = _derived_material_name(row)
        item_snapshot = {
            "item_id": int(row["item_id"]),
            "name": row["item_name"],
            "sku": row["item_sku"],
            "category": row["item_category"],
        }
        transformed_names[bom_id] = derived_name
        recovery_rows.append({
            "id": bom_id,
            "model_id": int(row["model_id"]),
            "before": {
                "item_id": int(row["item_id"]),
                "stock_batch_id": row["stock_batch_id"],
                "material_name": row["material_name"],
            },
            "item": item_snapshot,
            "after": {
                "item_id": None,
                "stock_batch_id": None,
                "material_name": derived_name,
            },
        })

    # 0107 ranks every Usluga BOM row with a non-null post-update name, including
    # inventory-independent names introduced by 0106.
    existing_named_rows = connection.execute(
        sa.select(bom.c.id, bom.c.model_id, bom.c.item_id, bom.c.stock_batch_id, bom.c.material_name)
        .select_from(bom.join(models, bom.c.model_id == models.c.id))
        .where(models.c.catalog_scope == "usluga", bom.c.material_name.is_not(None))
        .order_by(bom.c.model_id, bom.c.id)
    ).mappings().all()
    ranking_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in existing_named_rows:
        bom_id = int(row["id"])
        model_id = int(row["model_id"])
        ranking_rows[model_id].append({
            "id": bom_id,
            "model_id": model_id,
            "material_name_after": transformed_names.get(bom_id, row["material_name"]),
            "item_id_before": row["item_id"],
            "stock_batch_id_before": row["stock_batch_id"],
        })
    # A target row with a NULL manual name is absent from the existing-name
    # query, but becomes rankable after the item-name backfill above.
    for snapshot in recovery_rows:
        bom_id = snapshot["id"]
        if not any(entry["id"] == bom_id for entry in ranking_rows[snapshot["model_id"]]):
            ranking_rows[snapshot["model_id"]].append({
                "id": bom_id,
                "model_id": snapshot["model_id"],
                "material_name_after": snapshot["after"]["material_name"],
                "item_id_before": snapshot["before"]["item_id"],
                "stock_batch_id_before": snapshot["before"]["stock_batch_id"],
            })

    ranked_rows = []
    for model_id in sorted(ranking_rows):
        rows = sorted(ranking_rows[model_id], key=lambda entry: entry["id"])
        for position, row in enumerate(rows, start=1):
            ranked_rows.append({**row, "position": position,
                                "material_role_after": "main" if position == 1 else "secondary"})

    # Recreate the one-match-only bundle link rule; multi-match bundles remain
    # unlinked and are explicitly identified for operator review.
    join_rows = connection.execute(
        sa.select(bundles.c.id.label("bundle_id"), bundles.c.production_order_id,
                  bundles.c.production_batch_id, cutting_records.c.id.label("cutting_record_id"))
        .select_from(
            bundles.join(work_orders,
                         sa.and_(work_orders.c.production_order_id == bundles.c.production_order_id,
                                 work_orders.c.operation == "cutting"))
            .join(cutting_records,
                  sa.and_(cutting_records.c.work_order_id == work_orders.c.id,
                          cutting_records.c.production_batch_id.is_not_distinct_from(
                              bundles.c.production_batch_id)))
        )
        .order_by(bundles.c.id, cutting_records.c.id)
    ).mappings().all()
    bundle_matches: dict[int, dict[str, Any]] = {}
    for row in join_rows:
        bundle_id = int(row["bundle_id"])
        match = bundle_matches.setdefault(bundle_id, {
            "bundle_id": bundle_id,
            "production_order_id": row["production_order_id"],
            "production_batch_id": row["production_batch_id"],
            "cutting_record_ids": [],
        })
        match["cutting_record_ids"].append(int(row["cutting_record_id"]))
    auto_link_rows = []
    ambiguous_rows = []
    for bundle_id in sorted(bundle_matches):
        match = bundle_matches[bundle_id]
        if len(match["cutting_record_ids"]) == 1:
            auto_link_rows.append({
                "bundle_id": bundle_id,
                "production_order_id": match["production_order_id"],
                "production_batch_id": match["production_batch_id"],
                "cutting_record_id_after": match["cutting_record_ids"][0],
            })
        else:
            ambiguous_rows.append(match)
    bundle_count = int(connection.execute(sa.select(sa.func.count()).select_from(bundles)).scalar_one())
    no_match_count = bundle_count - len(bundle_matches)

    # The new non-null server-default assigns "approved" to all pre-existing
    # cutting records. Hash the complete target identity set for review.
    cutting_record_ids = [int(value) for value in connection.execute(
        sa.select(cutting_records.c.id).order_by(cutting_records.c.id)
    ).scalars()]

    # The role UPDATE always touches matching rows, but appends only when the
    # exact permission is absent. Keep the original JSON for restoration.
    role_rows = connection.execute(
        sa.select(roles.c.id, roles.c.name, roles.c.permissions, roles.c.updated_at)
        .where(sa.func.lower(roles.c.name) == "eco cotton usluga")
        .order_by(roles.c.id)
    ).mappings().all()
    role_snapshots = []
    for row in role_rows:
        before = row["permissions"]
        after = _jsonb_append_permission(before)
        restoration_snapshot = {
            "permissions": before,
            "updated_at": row["updated_at"],
        }
        role_snapshots.append({
            "role_id": int(row["id"]),
            "restoration_snapshot": restoration_snapshot,
            "after_permissions": after,
            "changed": before != after,
            "updated_at_will_be_refreshed": True,
            "snapshot_sha256": _snapshot_hash(restoration_snapshot),
            "after_sha256": _snapshot_hash({"permissions": after}),
        })

    return {
        "revision": REVISION_0107,
        "expected_predecessor": PREDECESSOR_0107,
        "database_revisions": current_revisions,
        "migration_pending": True,
        "applicability": (
            "manual_review_required" if ambiguous_rows or len(role_snapshots) > 1
            else "ready_for_operator_review"
        ),
        "affected_rows_inspected": True,
        "usluga_fabric_inventory_links": {
            "count": len(recovery_rows),
            "ids": [row["id"] for row in recovery_rows],
            "restoration_rows": recovery_rows,
            "snapshot_sha256": _snapshot_hash(recovery_rows),
        },
        "usluga_material_roles": {
            "count": len(ranked_rows),
            "main_count": sum(row["position"] == 1 for row in ranked_rows),
            "secondary_count": sum(row["position"] > 1 for row in ranked_rows),
            "rows": ranked_rows,
            "snapshot_sha256": _snapshot_hash(ranked_rows),
        },
        "existing_cutting_records_defaulted_approved": {
            "count": len(cutting_record_ids),
            "ids": cutting_record_ids,
            "snapshot_sha256": _snapshot_hash({
                "rows": [{"id": record_id, "approval_status_after": "approved"}
                         for record_id in cutting_record_ids]
            }),
        },
        "bundle_cutting_record_links": {
            "bundle_count": bundle_count,
            "auto_link_count": len(auto_link_rows),
            "auto_links": auto_link_rows,
            "auto_link_snapshot_sha256": _snapshot_hash(auto_link_rows),
            "ambiguous_count": len(ambiguous_rows),
            "ambiguous_bundles": ambiguous_rows,
            "ambiguous_snapshot_sha256": _snapshot_hash(ambiguous_rows),
            "no_match_count": no_match_count,
        },
        "eco_cotton_usluga_role": {
            "matching_role_count": len(role_snapshots),
            "changed_role_count": sum(role["changed"] for role in role_snapshots),
            "roles": role_snapshots,
            "snapshot_sha256": _snapshot_hash(role_snapshots),
        },
        "limitations": (
            "Preview covers only declared 0107 predicates at the exact predecessor. "
            "The bundle query follows declared work_order/cutting_record joins; "
            "application-level associations are not inspected. Hashes identify "
            "reviewed snapshots and are not backups. Role updated_at values are "
            "refreshed by 0107 even when permission content is already present. "
            "No migration is approved."
        ),
    }


def read_only_preflight_0107(engine: sa.Engine) -> dict[str, Any]:
    """Run the preview in one read-only transaction when supported."""
    with engine.connect() as connection:
        with connection.begin():
            if connection.dialect.name == "postgresql":
                connection.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            return preview_0107(connection)

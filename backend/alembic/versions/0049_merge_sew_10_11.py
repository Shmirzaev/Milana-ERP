"""merge duplicate sewing lines SEW-10 and SEW-11

Revision ID: 0049_merge_sew_10_11
Revises: 0048_simple_branded_numbers
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0049_merge_sew_10_11"
down_revision = "0048_simple_branded_numbers"
branch_labels = None
depends_on = None


TARGET_CODE = "SEW-10"
TARGET_NAME = "Nargiza opa"
SOURCE_CODE = "SEW-11"


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, code, name, capacity_per_day "
            "FROM sewing_flows WHERE code IN (:target_code, :source_code)"
        ),
        {"target_code": TARGET_CODE, "source_code": SOURCE_CODE},
    ).mappings().all()
    by_code = {row["code"]: row for row in rows}
    target = by_code.get(TARGET_CODE)
    source = by_code.get(SOURCE_CODE)
    if target is None:
        return

    target_id = int(target["id"])
    merged_capacity = int(target["capacity_per_day"] or 0)
    if source is not None:
        source_id = int(source["id"])
        merged_capacity += int(source["capacity_per_day"] or 0)
        for table in ("work_orders", "sewing_assignments", "sewing_daily_reports"):
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET sewing_flow_id = :target_id "
                    "WHERE sewing_flow_id = :source_id"
                ),
                {"target_id": target_id, "source_id": source_id},
            )

        bind.execute(
            sa.text(
                "UPDATE sewing_flows SET is_active = false, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = :source_id"
            ),
            {"source_id": source_id},
        )

    bind.execute(
        sa.text(
            "UPDATE sewing_flows "
            "SET name = :name, description = :description, capacity_per_day = :capacity, "
            "is_active = true, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = :target_id"
        ),
        {
            "name": TARGET_NAME,
            "description": "Consolidated sewing line (SEW-10, SEW-11)",
            "capacity": merged_capacity,
            "target_id": target_id,
        },
    )
    bind.execute(
        sa.text(
            "UPDATE sewing_daily_reports SET line_code = :code, line_name = :name "
            "WHERE sewing_flow_id = :target_id"
        ),
        {"code": TARGET_CODE, "name": TARGET_NAME, "target_id": target_id},
    )

    old_labels = {
        TARGET_CODE.lower(),
        TARGET_NAME.lower(),
        SOURCE_CODE.lower(),
        *(str(row["name"]).lower() for row in rows),
    }
    label_params = {f"label_{index}": label for index, label in enumerate(sorted(old_labels))}
    placeholders = ", ".join(f":label_{index}" for index in range(len(label_params)))
    bind.execute(
        sa.text(
            "UPDATE sewing_records SET line_name = :name "
            f"WHERE lower(line_name) IN ({placeholders})"
        ),
        {"name": TARGET_NAME, **label_params},
    )


def downgrade():
    # References cannot be split reliably after the merge, but the duplicate
    # catalog row can be made visible again if a rollback is required.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE sewing_flows SET name = 'Nargiza opa', capacity_per_day = 200, "
            "is_active = true, updated_at = CURRENT_TIMESTAMP WHERE code = 'SEW-10'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE sewing_flows SET name = 'Maxmudova Nargiza', capacity_per_day = 200, "
            "is_active = true, updated_at = CURRENT_TIMESTAMP WHERE code = 'SEW-11'"
        )
    )

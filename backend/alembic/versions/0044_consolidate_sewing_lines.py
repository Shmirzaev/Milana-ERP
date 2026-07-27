"""consolidate and rename sewing lines

Revision ID: 0044_consolidate_sewing_lines
Revises: 0043_activate_sewing_lines_11_13
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0044_consolidate_sewing_lines"
down_revision = "0043_activate_sewing_lines_11_13"
branch_labels = None
depends_on = None


# The first code in each group is the surviving identity. Keeping the
# established IDs prevents current clients and saved links from breaking.
LINE_GROUPS = (
    ("SEW-01", "Bozorova", ("SEW-01", "SEW-02", "SEW-08")),
    ("SEW-06", "Shaxnoza opa", ("SEW-06",)),
    ("SEW-07", "Jalilova", ("SEW-07", "SEW-05", "SEW-04", "SEW-03")),
    ("SEW-09", "Dilafruz opa", ("SEW-09",)),
    ("SEW-10", "Nargiza opa", ("SEW-10",)),
    ("SEW-11", "Maxmudova Nargiza", ("SEW-11",)),
    ("SEW-12", "Muxlisa", ("SEW-12",)),
    ("SEW-13", "Sevara", ("SEW-13",)),
)


def _flow_rows(bind, codes):
    params = {f"code_{index}": code for index, code in enumerate(codes)}
    placeholders = ", ".join(f":code_{index}" for index in range(len(codes)))
    rows = bind.execute(
        sa.text(
            "SELECT id, code, name, capacity_per_day "
            f"FROM sewing_flows WHERE code IN ({placeholders})"
        ),
        params,
    ).mappings().all()
    return rows


def upgrade():
    bind = op.get_bind()

    for target_code, target_name, codes in LINE_GROUPS:
        rows = _flow_rows(bind, codes)
        by_code = {row["code"]: row for row in rows}
        target = by_code.get(target_code)
        # On a brand-new deployment the seed runs after Alembic and creates
        # the canonical rows, so an absent target here is expected and safe.
        if target is None:
            continue

        target_id = int(target["id"])
        source_ids = [int(row["id"]) for row in rows if row["code"] != target_code]
        all_ids = [target_id, *source_ids]
        merged_capacity = sum(int(row["capacity_per_day"] or 0) for row in rows)

        if source_ids:
            id_params = {f"id_{index}": flow_id for index, flow_id in enumerate(source_ids)}
            id_placeholders = ", ".join(f":id_{index}" for index in range(len(source_ids)))
            for table in ("work_orders", "sewing_assignments", "sewing_daily_reports"):
                bind.execute(
                    sa.text(
                        f"UPDATE {table} SET sewing_flow_id = :target_id "
                        f"WHERE sewing_flow_id IN ({id_placeholders})"
                    ),
                    {"target_id": target_id, **id_params},
                )

        bind.execute(
            sa.text(
                "UPDATE sewing_flows "
                "SET name = :name, description = :description, "
                "capacity_per_day = :capacity, is_active = true, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = :target_id"
            ),
            {
                "name": target_name,
                "description": f"Consolidated sewing line ({', '.join(codes)})",
                "capacity": merged_capacity,
                "target_id": target_id,
            },
        )

        if source_ids:
            id_params = {f"all_id_{index}": flow_id for index, flow_id in enumerate(all_ids)}
            id_placeholders = ", ".join(f":all_id_{index}" for index in range(len(all_ids)))
            source_params = {f"source_id_{index}": flow_id for index, flow_id in enumerate(source_ids)}
            source_placeholders = ", ".join(f":source_id_{index}" for index in range(len(source_ids)))
            bind.execute(
                sa.text(
                    "UPDATE sewing_daily_reports "
                    "SET line_code = :code, line_name = :name "
                    f"WHERE sewing_flow_id IN ({id_placeholders})"
                ),
                {"code": target_code, "name": target_name, **id_params},
            )
            bind.execute(
                sa.text(
                    "UPDATE sewing_flows SET is_active = false, updated_at = CURRENT_TIMESTAMP "
                    f"WHERE id IN ({source_placeholders})"
                ),
                source_params,
            )
        else:
            bind.execute(
                sa.text(
                    "UPDATE sewing_daily_reports SET line_code = :code, line_name = :name "
                    "WHERE sewing_flow_id = :target_id"
                ),
                {"code": target_code, "name": target_name, "target_id": target_id},
            )

        # Sewing records predate a flow FK and store either the old code or
        # the old display name. Normalize both forms to the new visible name.
        old_labels = {str(row["code"]).lower() for row in rows}
        old_labels.update(str(row["name"]).lower() for row in rows)
        label_params = {f"label_{index}": label for index, label in enumerate(sorted(old_labels))}
        label_placeholders = ", ".join(f":label_{index}" for index in range(len(label_params)))
        bind.execute(
            sa.text(
                "UPDATE sewing_records SET line_name = :name "
                f"WHERE lower(line_name) IN ({label_placeholders})"
            ),
            {"name": target_name, **label_params},
        )


def downgrade():
    # Recreate the former catalog. Work/report references cannot be split back
    # reliably because the merge intentionally discards that distinction.
    bind = op.get_bind()
    for line_number in range(1, 14):
        code = f"SEW-{line_number:02d}"
        bind.execute(
            sa.text(
                "UPDATE sewing_flows "
                "SET name = :name, description = :description, "
                "capacity_per_day = 200, is_active = true, updated_at = CURRENT_TIMESTAMP "
                "WHERE code = :code"
            ),
            {
                "name": f"Line {line_number:02d}",
                "description": f"Sewing flow Line {line_number:02d}",
                "code": code,
            },
        )

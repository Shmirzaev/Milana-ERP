"""add Usluga fabric roles and cutting batch approval

Revision ID: 0107_usluga_cutting_approval
Revises: 0106_usluga_manual_fabric
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0107_usluga_cutting_approval"
down_revision = "0106_usluga_manual_fabric"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_bom", sa.Column("material_role", sa.String(length=16), nullable=True))

    # Existing Usluga fabric specifications become independent text rows. The
    # first fabric is the main material; further fabrics are secondary.
    op.execute(
        """
        UPDATE model_bom AS mb
           SET material_name = COALESCE(NULLIF(btrim(i.name), ''), NULLIF(btrim(i.sku), ''), 'Fabric #' || i.id::text),
               item_id = NULL,
               stock_batch_id = NULL
          FROM models AS m, items AS i
         WHERE mb.model_id = m.id
           AND mb.item_id = i.id
           AND m.catalog_scope = 'usluga'
           AND lower(COALESCE(i.category, '')) IN ('fabric', 'semi_finished')
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT mb.id,
                   row_number() OVER (PARTITION BY mb.model_id ORDER BY mb.id) AS position
              FROM model_bom AS mb
              JOIN models AS m ON m.id = mb.model_id
             WHERE m.catalog_scope = 'usluga'
               AND mb.material_name IS NOT NULL
        )
        UPDATE model_bom AS mb
           SET material_role = CASE WHEN ranked.position = 1 THEN 'main' ELSE 'secondary' END
          FROM ranked
         WHERE ranked.id = mb.id
        """
    )
    op.create_check_constraint(
        "ck_model_bom_material_role",
        "model_bom",
        "(material_name IS NULL AND material_role IS NULL) OR "
        "(material_name IS NOT NULL AND material_role IN ('main', 'secondary'))",
    )
    op.create_index(
        "uq_model_bom_main_material_per_model",
        "model_bom",
        ["model_id"],
        unique=True,
        postgresql_where=sa.text("material_role = 'main'"),
    )

    op.add_column("cutting_records", sa.Column("model_bom_id", sa.Integer(), nullable=True))
    op.add_column("cutting_records", sa.Column("cutting_batch_no", sa.String(length=64), nullable=True))
    op.add_column("cutting_records", sa.Column("material_name_snapshot", sa.String(length=255), nullable=True))
    op.add_column("cutting_records", sa.Column("material_role", sa.String(length=16), nullable=True))
    op.add_column(
        "cutting_records",
        sa.Column("approval_status", sa.String(length=16), server_default="approved", nullable=False),
    )
    op.add_column("cutting_records", sa.Column("approved_by", sa.Integer(), nullable=True))
    op.add_column("cutting_records", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cutting_records", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.create_foreign_key("fk_cutting_records_model_bom", "cutting_records", "model_bom", ["model_bom_id"], ["id"])
    op.create_foreign_key("fk_cutting_records_approved_by", "cutting_records", "users", ["approved_by"], ["id"])
    op.create_check_constraint(
        "ck_cutting_records_material_role",
        "cutting_records",
        "material_role IS NULL OR material_role IN ('main', 'secondary')",
    )
    op.create_check_constraint(
        "ck_cutting_records_approval_status",
        "cutting_records",
        "approval_status IN ('pending', 'approved', 'rejected')",
    )
    op.create_index("ix_cutting_records_model_bom_id", "cutting_records", ["model_bom_id"])
    op.create_index("ix_cutting_records_approval_status", "cutting_records", ["approval_status"])
    op.create_index("ix_cutting_records_cutting_batch_no", "cutting_records", ["cutting_batch_no"], unique=True)

    op.add_column("bundles", sa.Column("cutting_record_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_bundles_cutting_record", "bundles", "cutting_records", ["cutting_record_id"], ["id"])
    op.create_index("ix_bundles_cutting_record_id", "bundles", ["cutting_record_id"])
    op.execute(
        """
        UPDATE bundles AS b
           SET cutting_record_id = matches.record_id
          FROM (
                SELECT b2.id AS bundle_id, min(cr.id) AS record_id
                  FROM bundles AS b2
                  JOIN work_orders AS wo
                    ON wo.production_order_id = b2.production_order_id
                   AND wo.operation = 'cutting'
                  JOIN cutting_records AS cr
                    ON cr.work_order_id = wo.id
                   AND cr.production_batch_id IS NOT DISTINCT FROM b2.production_batch_id
                 GROUP BY b2.id
                HAVING count(cr.id) = 1
          ) AS matches
         WHERE matches.bundle_id = b.id
        """
    )

    op.execute(
        """
        UPDATE roles
           SET permissions = CASE
               WHEN permissions::jsonb ? 'usluga.cutting.approve' THEN permissions
               ELSE (permissions::jsonb || '["usluga.cutting.approve"]'::jsonb)::json
           END,
               updated_at = CURRENT_TIMESTAMP
         WHERE lower(name) = 'eco cotton usluga'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
           SET permissions = (SELECT COALESCE(jsonb_agg(value), '[]'::jsonb)::json
                                FROM jsonb_array_elements_text(permissions::jsonb) AS value
                               WHERE value <> 'usluga.cutting.approve'),
               updated_at = CURRENT_TIMESTAMP
         WHERE lower(name) = 'eco cotton usluga'
        """
    )
    op.drop_index("ix_bundles_cutting_record_id", table_name="bundles")
    op.drop_constraint("fk_bundles_cutting_record", "bundles", type_="foreignkey")
    op.drop_column("bundles", "cutting_record_id")

    op.drop_index("ix_cutting_records_cutting_batch_no", table_name="cutting_records")
    op.drop_index("ix_cutting_records_approval_status", table_name="cutting_records")
    op.drop_index("ix_cutting_records_model_bom_id", table_name="cutting_records")
    op.drop_constraint("ck_cutting_records_approval_status", "cutting_records", type_="check")
    op.drop_constraint("ck_cutting_records_material_role", "cutting_records", type_="check")
    op.drop_constraint("fk_cutting_records_approved_by", "cutting_records", type_="foreignkey")
    op.drop_constraint("fk_cutting_records_model_bom", "cutting_records", type_="foreignkey")
    op.drop_column("cutting_records", "rejection_reason")
    op.drop_column("cutting_records", "approved_at")
    op.drop_column("cutting_records", "approved_by")
    op.drop_column("cutting_records", "approval_status")
    op.drop_column("cutting_records", "material_role")
    op.drop_column("cutting_records", "material_name_snapshot")
    op.drop_column("cutting_records", "cutting_batch_no")
    op.drop_column("cutting_records", "model_bom_id")

    op.drop_index("uq_model_bom_main_material_per_model", table_name="model_bom")
    op.drop_constraint("ck_model_bom_material_role", "model_bom", type_="check")
    op.drop_column("model_bom", "material_role")

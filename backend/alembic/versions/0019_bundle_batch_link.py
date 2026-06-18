"""add batch link to bundles

Revision ID: 0019_bundle_batch_link
Revises: 0018_user_activity_timestamps
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa


revision = "0019_bundle_batch_link"
down_revision = "0018_user_activity_timestamps"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "bundles" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("bundles")}
    if "production_batch_id" not in columns:
        op.add_column("bundles", sa.Column("production_batch_id", sa.Integer(), nullable=True))
        columns.add("production_batch_id")

    if "production_batch_id" in columns:
        fks = inspector.get_foreign_keys("bundles")
        has_fk = any("production_batch_id" in (fk.get("constrained_columns") or []) for fk in fks)
        if not has_fk:
            op.create_foreign_key(
                "fk_bundles_production_batch_id",
                "bundles",
                "production_batches",
                ["production_batch_id"],
                ["id"],
            )
        indexes = inspector.get_indexes("bundles")
        if not any(ix.get("name") == op.f("ix_bundles_production_batch_id") for ix in indexes):
            op.create_index(op.f("ix_bundles_production_batch_id"), "bundles", ["production_batch_id"], unique=False)

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            WITH bundle_rank AS (
                SELECT
                    id,
                    production_order_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY production_order_id
                        ORDER BY created_at, id
                    ) AS rn
                FROM bundles
                WHERE production_batch_id IS NULL
            ),
            cutting_ranges AS (
                SELECT
                    wo.production_order_id,
                    cr.production_batch_id,
                    SUM(cr.bundle_count) OVER (
                        PARTITION BY wo.production_order_id
                        ORDER BY cr.created_at, cr.id
                    ) - cr.bundle_count + 1 AS start_rn,
                    SUM(cr.bundle_count) OVER (
                        PARTITION BY wo.production_order_id
                        ORDER BY cr.created_at, cr.id
                    ) AS end_rn
                FROM cutting_records cr
                JOIN work_orders wo ON wo.id = cr.work_order_id
                WHERE cr.production_batch_id IS NOT NULL
                  AND cr.bundle_count > 0
            )
            UPDATE bundles b
            SET production_batch_id = cr.production_batch_id
            FROM bundle_rank br
            JOIN cutting_ranges cr
              ON cr.production_order_id = br.production_order_id
             AND br.rn BETWEEN cr.start_rn AND cr.end_rn
            WHERE b.id = br.id
              AND b.production_batch_id IS NULL
            """
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "bundles" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("bundles")}
    if "production_batch_id" in columns:
        indexes = inspector.get_indexes("bundles")
        if any(ix.get("name") == op.f("ix_bundles_production_batch_id") for ix in indexes):
            op.drop_index(op.f("ix_bundles_production_batch_id"), table_name="bundles")
        fks = inspector.get_foreign_keys("bundles")
        fk_names = [fk.get("name") for fk in fks if "production_batch_id" in (fk.get("constrained_columns") or [])]
        for fk_name in fk_names:
            if fk_name:
                op.drop_constraint(fk_name, "bundles", type_="foreignkey")
        op.drop_column("bundles", "production_batch_id")

"""add production batches and batch link for work orders

Revision ID: 0006_production_batches
Revises: 0005_sales_order_printing_fields
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_production_batches"
down_revision = "0005_sales_order_printing_fields"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())
    if "production_batches" not in tables:
        op.create_table(
            "production_batches",
            sa.Column("production_order_id", sa.Integer(), nullable=False),
            sa.Column("batch_no", sa.String(length=32), nullable=False),
            sa.Column("batch_index", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("name", sa.String(length=128), nullable=True),
            sa.Column("planned_quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["production_order_id"], ["production_orders.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_production_batches_production_order_id"), "production_batches", ["production_order_id"], unique=False)

    cols = {c.get("name") for c in inspector.get_columns("work_orders")}
    if "production_batch_id" not in cols:
        op.add_column("work_orders", sa.Column("production_batch_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_work_orders_production_batch_id",
            "work_orders",
            "production_batches",
            ["production_batch_id"],
            ["id"],
        )

    for table in ("printing_records", "sewing_records", "packaging_records", "cutting_records"):
        cols = {c.get("name") for c in inspector.get_columns(table)}
        if "production_batch_id" not in cols:
            op.add_column(table, sa.Column("production_batch_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                f"fk_{table}_production_batch_id",
                table,
                "production_batches",
                ["production_batch_id"],
                ["id"],
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c.get("name") for c in inspector.get_columns("work_orders")}
    if "production_batch_id" in cols:
        fks = inspector.get_foreign_keys("work_orders")
        fk_names = [fk.get("name") for fk in fks if "production_batch_id" in (fk.get("constrained_columns") or [])]
        for fk_name in fk_names:
            if fk_name:
                op.drop_constraint(fk_name, "work_orders", type_="foreignkey")
        op.drop_column("work_orders", "production_batch_id")

    for table in ("packaging_records", "sewing_records", "printing_records", "cutting_records"):
        cols = {c.get("name") for c in inspector.get_columns(table)}
        if "production_batch_id" in cols:
            fks = inspector.get_foreign_keys(table)
            fk_names = [fk.get("name") for fk in fks if "production_batch_id" in (fk.get("constrained_columns") or [])]
            for fk_name in fk_names:
                if fk_name:
                    op.drop_constraint(fk_name, table, type_="foreignkey")
            op.drop_column(table, "production_batch_id")

    tables = set(inspector.get_table_names())
    if "production_batches" in tables:
        op.drop_index(op.f("ix_production_batches_production_order_id"), table_name="production_batches")
        op.drop_table("production_batches")

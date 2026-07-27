"""track sewing work received by packaging

Revision ID: 0052_packaging_receipts
Revises: 0051_sewing_section_order
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0052_packaging_receipts"
down_revision = "0051_sewing_section_order"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "packaging_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("source_work_order_id", sa.Integer(), nullable=False),
        sa.Column("production_order_id", sa.Integer(), nullable=False),
        sa.Column("production_batch_id", sa.Integer(), nullable=True),
        sa.Column("bundle_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("receive_method", sa.String(length=16), nullable=False),
        sa.Column("received_by", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_packaging_receipts_quantity_positive"),
        sa.CheckConstraint("receive_method IN ('scan', 'manual')", name="ck_packaging_receipts_method"),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"]),
        sa.ForeignKeyConstraint(["production_batch_id"], ["production_batches.id"]),
        sa.ForeignKeyConstraint(["production_order_id"], ["production_orders.id"]),
        sa.ForeignKeyConstraint(["received_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_work_order_id"], ["work_orders.id"]),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bundle_id", name="uq_packaging_receipts_bundle"),
    )
    op.create_index("ix_packaging_receipts_work_order_id", "packaging_receipts", ["work_order_id"])
    op.create_index("ix_packaging_receipts_source_work_order_id", "packaging_receipts", ["source_work_order_id"])
    op.create_index("ix_packaging_receipts_production_order_id", "packaging_receipts", ["production_order_id"])
    op.create_index("ix_packaging_receipts_production_batch_id", "packaging_receipts", ["production_batch_id"])
    op.create_index("ix_packaging_receipts_bundle_id", "packaging_receipts", ["bundle_id"])


def downgrade():
    op.drop_index("ix_packaging_receipts_bundle_id", table_name="packaging_receipts")
    op.drop_index("ix_packaging_receipts_production_batch_id", table_name="packaging_receipts")
    op.drop_index("ix_packaging_receipts_production_order_id", table_name="packaging_receipts")
    op.drop_index("ix_packaging_receipts_source_work_order_id", table_name="packaging_receipts")
    op.drop_index("ix_packaging_receipts_work_order_id", table_name="packaging_receipts")
    op.drop_table("packaging_receipts")

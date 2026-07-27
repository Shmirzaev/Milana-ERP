"""track sewing failures that must be cut and sewn again

Revision ID: 0060_sewing_replacements
Revises: 0059_sewing_report_manual_model
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0060_sewing_replacements"
down_revision = "0059_sewing_report_manual_model"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sewing_replacement_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("production_order_id", sa.Integer(), nullable=False),
        sa.Column("sewing_work_order_id", sa.Integer(), nullable=False),
        sa.Column("cutting_work_order_id", sa.Integer(), nullable=True),
        sa.Column("production_batch_id", sa.Integer(), nullable=True),
        sa.Column("sewing_record_id", sa.Integer(), nullable=False),
        sa.Column("requested_qty", sa.Integer(), nullable=False),
        sa.Column("cut_qty", sa.Integer(), server_default="0", nullable=False),
        sa.Column("replaced_qty", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="waiting_cutting", nullable=False),
        sa.Column("defect_reason", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("requested_qty > 0", name="ck_sewing_replacements_requested_positive"),
        sa.CheckConstraint("cut_qty >= 0", name="ck_sewing_replacements_cut_nonnegative"),
        sa.CheckConstraint("replaced_qty >= 0", name="ck_sewing_replacements_replaced_nonnegative"),
        sa.CheckConstraint("cut_qty <= requested_qty", name="ck_sewing_replacements_cut_lte_requested"),
        sa.CheckConstraint("replaced_qty <= requested_qty", name="ck_sewing_replacements_replaced_lte_requested"),
        sa.CheckConstraint(
            "status IN ('waiting_cutting', 'waiting_sewing', 'completed')",
            name="ck_sewing_replacements_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["cutting_work_order_id"], ["work_orders.id"]),
        sa.ForeignKeyConstraint(["production_batch_id"], ["production_batches.id"]),
        sa.ForeignKeyConstraint(["production_order_id"], ["production_orders.id"]),
        sa.ForeignKeyConstraint(["sewing_record_id"], ["sewing_records.id"]),
        sa.ForeignKeyConstraint(["sewing_work_order_id"], ["work_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sewing_record_id", name="uq_sewing_replacements_sewing_record"),
    )
    op.create_index("ix_sewing_replacements_production_order_id", "sewing_replacement_requests", ["production_order_id"])
    op.create_index("ix_sewing_replacements_sewing_work_order_id", "sewing_replacement_requests", ["sewing_work_order_id"])
    op.create_index("ix_sewing_replacements_cutting_work_order_id", "sewing_replacement_requests", ["cutting_work_order_id"])
    op.create_index("ix_sewing_replacements_production_batch_id", "sewing_replacement_requests", ["production_batch_id"])
    op.create_index("ix_sewing_replacements_status", "sewing_replacement_requests", ["status"])


def downgrade():
    op.drop_index("ix_sewing_replacements_status", table_name="sewing_replacement_requests")
    op.drop_index("ix_sewing_replacements_production_batch_id", table_name="sewing_replacement_requests")
    op.drop_index("ix_sewing_replacements_cutting_work_order_id", table_name="sewing_replacement_requests")
    op.drop_index("ix_sewing_replacements_sewing_work_order_id", table_name="sewing_replacement_requests")
    op.drop_index("ix_sewing_replacements_production_order_id", table_name="sewing_replacement_requests")
    op.drop_table("sewing_replacement_requests")

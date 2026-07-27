"""sewing daily reports

Revision ID: 0040_sewing_daily_reports
Revises: 0039_manual_accessory_issues
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa


revision = "0040_sewing_daily_reports"
down_revision = "0039_manual_accessory_issues"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sewing_daily_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("sewing_flow_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("sewing_assignment_id", sa.Integer(), nullable=True),
        sa.Column("production_order_id", sa.Integer(), nullable=True),
        sa.Column("production_batch_id", sa.Integer(), nullable=True),
        sa.Column("line_code", sa.String(length=32), nullable=False),
        sa.Column("line_name", sa.String(length=64), nullable=False),
        sa.Column("order_no", sa.String(length=64), nullable=True),
        sa.Column("production_no", sa.String(length=64), nullable=True),
        sa.Column("sales_order_no", sa.String(length=64), nullable=True),
        sa.Column("sewn_qty", sa.Integer(), nullable=False),
        sa.Column("defective_qty", sa.Integer(), nullable=False),
        sa.Column("defect_reason", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("sewn_qty >= 0", name="ck_sewing_daily_reports_sewn_nonnegative"),
        sa.CheckConstraint("defective_qty >= 0", name="ck_sewing_daily_reports_defective_nonnegative"),
        sa.CheckConstraint("defective_qty <= sewn_qty", name="ck_sewing_daily_reports_defective_lte_sewn"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["production_batch_id"], ["production_batches.id"]),
        sa.ForeignKeyConstraint(["production_order_id"], ["production_orders.id"]),
        sa.ForeignKeyConstraint(["sewing_assignment_id"], ["sewing_assignments.id"]),
        sa.ForeignKeyConstraint(["sewing_flow_id"], ["sewing_flows.id"]),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sewing_daily_reports_report_date"), "sewing_daily_reports", ["report_date"], unique=False)
    op.create_index(op.f("ix_sewing_daily_reports_sewing_assignment_id"), "sewing_daily_reports", ["sewing_assignment_id"], unique=False)
    op.create_index(op.f("ix_sewing_daily_reports_sewing_flow_id"), "sewing_daily_reports", ["sewing_flow_id"], unique=False)
    op.create_index(op.f("ix_sewing_daily_reports_work_order_id"), "sewing_daily_reports", ["work_order_id"], unique=False)
    op.create_index(op.f("ix_sewing_daily_reports_production_order_id"), "sewing_daily_reports", ["production_order_id"], unique=False)
    op.create_index(op.f("ix_sewing_daily_reports_production_batch_id"), "sewing_daily_reports", ["production_batch_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_sewing_daily_reports_production_batch_id"), table_name="sewing_daily_reports")
    op.drop_index(op.f("ix_sewing_daily_reports_production_order_id"), table_name="sewing_daily_reports")
    op.drop_index(op.f("ix_sewing_daily_reports_work_order_id"), table_name="sewing_daily_reports")
    op.drop_index(op.f("ix_sewing_daily_reports_sewing_flow_id"), table_name="sewing_daily_reports")
    op.drop_index(op.f("ix_sewing_daily_reports_sewing_assignment_id"), table_name="sewing_daily_reports")
    op.drop_index(op.f("ix_sewing_daily_reports_report_date"), table_name="sewing_daily_reports")
    op.drop_table("sewing_daily_reports")

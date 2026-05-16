"""add planning estimate fields to sales_orders

Revision ID: 0002_plan_estimate_fields
Revises: 0001_initial
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_plan_estimate_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sales_orders", sa.Column("planning_estimated_material_cost", sa.Numeric(14, 2), nullable=True))
    op.add_column("sales_orders", sa.Column("planning_estimated_lead_time_minutes", sa.Integer(), nullable=True))
    op.add_column("sales_orders", sa.Column("planning_estimate_comment", sa.Text(), nullable=True))
    op.add_column("sales_orders", sa.Column("planning_estimate_submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sales_orders", sa.Column("planning_estimate_submitted_by", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_sales_orders_planning_estimate_submitted_by_users",
        "sales_orders",
        "users",
        ["planning_estimate_submitted_by"],
        ["id"],
    )


def downgrade():
    op.drop_constraint("fk_sales_orders_planning_estimate_submitted_by_users", "sales_orders", type_="foreignkey")
    op.drop_column("sales_orders", "planning_estimate_submitted_by")
    op.drop_column("sales_orders", "planning_estimate_submitted_at")
    op.drop_column("sales_orders", "planning_estimate_comment")
    op.drop_column("sales_orders", "planning_estimated_lead_time_minutes")
    op.drop_column("sales_orders", "planning_estimated_material_cost")

"""add planning expense and suggested price fields to sales_orders

Revision ID: 0003_plan_expense_fields
Revises: 0002_plan_estimate_fields
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0003_plan_expense_fields"
down_revision = "0002_plan_estimate_fields"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("sales_orders")}

    if "planning_estimated_labor_cost" not in existing_cols:
        op.add_column("sales_orders", sa.Column("planning_estimated_labor_cost", sa.Numeric(14, 2), nullable=True))
    if "planning_estimated_electricity_cost" not in existing_cols:
        op.add_column("sales_orders", sa.Column("planning_estimated_electricity_cost", sa.Numeric(14, 2), nullable=True))
    if "planning_estimated_other_cost" not in existing_cols:
        op.add_column("sales_orders", sa.Column("planning_estimated_other_cost", sa.Numeric(14, 2), nullable=True))
    if "planning_estimated_net_cost" not in existing_cols:
        op.add_column("sales_orders", sa.Column("planning_estimated_net_cost", sa.Numeric(14, 2), nullable=True))
    if "planning_suggested_price_15" not in existing_cols:
        op.add_column("sales_orders", sa.Column("planning_suggested_price_15", sa.Numeric(14, 2), nullable=True))
    if "planning_suggested_price_20" not in existing_cols:
        op.add_column("sales_orders", sa.Column("planning_suggested_price_20", sa.Numeric(14, 2), nullable=True))


def downgrade():
    op.drop_column("sales_orders", "planning_suggested_price_20")
    op.drop_column("sales_orders", "planning_suggested_price_15")
    op.drop_column("sales_orders", "planning_estimated_net_cost")
    op.drop_column("sales_orders", "planning_estimated_other_cost")
    op.drop_column("sales_orders", "planning_estimated_electricity_cost")
    op.drop_column("sales_orders", "planning_estimated_labor_cost")

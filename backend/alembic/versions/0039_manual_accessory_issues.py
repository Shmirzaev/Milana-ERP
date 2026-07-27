"""manual accessory issues

Revision ID: 0039_manual_accessory_issues
Revises: 0038_lift_downstream_plans
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa


revision = "0039_manual_accessory_issues"
down_revision = "0038_lift_downstream_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manual_accessory_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("production_order_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("item_sku", sa.String(length=64), nullable=True),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["production_order_id"], ["production_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity > 0", name="ck_manual_accessory_issues_quantity_positive"),
    )
    op.create_index(op.f("ix_manual_accessory_issues_item_id"), "manual_accessory_issues", ["item_id"], unique=False)
    op.create_index(
        op.f("ix_manual_accessory_issues_production_order_id"),
        "manual_accessory_issues",
        ["production_order_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_manual_accessory_issues_production_order_id"), table_name="manual_accessory_issues")
    op.drop_index(op.f("ix_manual_accessory_issues_item_id"), table_name="manual_accessory_issues")
    op.drop_table("manual_accessory_issues")

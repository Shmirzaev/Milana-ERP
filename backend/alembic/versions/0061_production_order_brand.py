"""store the planner-selected brand on production orders

Revision ID: 0061_production_order_brand
Revises: 0060_sewing_replacements
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0061_production_order_brand"
down_revision = "0060_sewing_replacements"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "production_orders",
        sa.Column("brand_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_production_orders_brand_id_brands",
        "production_orders",
        "brands",
        ["brand_id"],
        ["id"],
    )
    op.create_index(
        "ix_production_orders_brand_id",
        "production_orders",
        ["brand_id"],
    )


def downgrade():
    op.drop_index("ix_production_orders_brand_id", table_name="production_orders")
    op.drop_constraint(
        "fk_production_orders_brand_id_brands",
        "production_orders",
        type_="foreignkey",
    )
    op.drop_column("production_orders", "brand_id")

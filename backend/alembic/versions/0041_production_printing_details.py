"""add print details to production orders

Revision ID: 0041_production_printing_details
Revises: 0040_sewing_daily_reports
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa


revision = "0041_production_printing_details"
down_revision = "0040_sewing_daily_reports"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    po_cols = {c.get("name") for c in inspector.get_columns("production_orders")}
    if "printing_instructions" not in po_cols:
        op.add_column("production_orders", sa.Column("printing_instructions", sa.Text(), nullable=True))
    if "printing_attachments" not in po_cols:
        op.add_column("production_orders", sa.Column("printing_attachments", sa.JSON(), nullable=True))

    item_cols = {c.get("name") for c in inspector.get_columns("production_order_items")}
    if "printing_required" not in item_cols:
        op.add_column(
            "production_order_items",
            sa.Column("printing_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column("production_order_items", "printing_required", server_default=None)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    item_cols = {c.get("name") for c in inspector.get_columns("production_order_items")}
    if "printing_required" in item_cols:
        op.drop_column("production_order_items", "printing_required")

    po_cols = {c.get("name") for c in inspector.get_columns("production_orders")}
    if "printing_attachments" in po_cols:
        op.drop_column("production_orders", "printing_attachments")
    if "printing_instructions" in po_cols:
        op.drop_column("production_orders", "printing_instructions")

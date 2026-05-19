"""add printing instructions and attachments to sales_orders

Revision ID: 0005_sales_order_printing_fields
Revises: 0004_model_details_json
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_sales_order_printing_fields"
down_revision = "0004_model_details_json"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c.get("name") for c in inspector.get_columns("sales_orders")}
    if "printing_instructions" not in cols:
        op.add_column("sales_orders", sa.Column("printing_instructions", sa.Text(), nullable=True))
    if "printing_attachments" not in cols:
        op.add_column("sales_orders", sa.Column("printing_attachments", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c.get("name") for c in inspector.get_columns("sales_orders")}
    if "printing_attachments" in cols:
        op.drop_column("sales_orders", "printing_attachments")
    if "printing_instructions" in cols:
        op.drop_column("sales_orders", "printing_instructions")

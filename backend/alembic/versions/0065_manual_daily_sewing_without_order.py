"""allow manual daily sewing reports without an order

Revision ID: 0065_manual_sewing_no_order
Revises: 0064_remove_fabric_pictures
Create Date: 2026-07-22
"""

from alembic import op


revision = "0065_manual_sewing_no_order"
down_revision = "0064_remove_fabric_pictures"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("sewing_daily_reports", "work_order_id", nullable=True)


def downgrade():
    op.alter_column("sewing_daily_reports", "work_order_id", nullable=False)

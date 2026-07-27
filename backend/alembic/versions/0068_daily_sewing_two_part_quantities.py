"""add two-part quantities to daily sewing reports

Revision ID: 0068_daily_sewing_two_parts
Revises: 0067_daily_sewing_section_name
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0068_daily_sewing_two_parts"
down_revision = "0067_daily_sewing_section_name"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sewing_daily_reports", sa.Column("top_qty", sa.Integer(), nullable=True))
    op.add_column("sewing_daily_reports", sa.Column("bottom_qty", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("sewing_daily_reports", "bottom_qty")
    op.drop_column("sewing_daily_reports", "top_qty")

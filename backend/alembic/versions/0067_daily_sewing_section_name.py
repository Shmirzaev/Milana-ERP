"""add section name to daily sewing reports

Revision ID: 0067_daily_sewing_section_name
Revises: 0066_daily_sewing_kroy_no
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0067_daily_sewing_section_name"
down_revision = "0066_daily_sewing_kroy_no"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sewing_daily_reports", sa.Column("section_name", sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column("sewing_daily_reports", "section_name")

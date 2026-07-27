"""store sewing daily report section quantities

Revision ID: 0050_sewing_report_sections
Revises: 0049_merge_sew_10_11
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0050_sewing_report_sections"
down_revision = "0049_merge_sew_10_11"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sewing_daily_reports", sa.Column("section_quantities", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("sewing_daily_reports", "section_quantities")

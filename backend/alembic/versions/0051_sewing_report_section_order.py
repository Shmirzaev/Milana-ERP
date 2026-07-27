"""identify the section and order for sewing daily reports

Revision ID: 0051_sewing_section_order
Revises: 0050_sewing_report_sections
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0051_sewing_section_order"
down_revision = "0050_sewing_report_sections"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sewing_daily_reports", sa.Column("section_no", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_sewing_daily_reports_section_no",
        "sewing_daily_reports",
        "section_no IS NULL OR section_no BETWEEN 1 AND 3",
    )


def downgrade():
    op.drop_constraint("ck_sewing_daily_reports_section_no", "sewing_daily_reports", type_="check")
    op.drop_column("sewing_daily_reports", "section_no")

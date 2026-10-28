"""allow up to twenty daily sewing report sections

Revision ID: 0072_sewing_report_sections
Revises: 0071_model_less_legacy_sales
"""

from alembic import op


revision = "0072_sewing_report_sections"
down_revision = "0071_model_less_legacy_sales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_sewing_daily_reports_section_no",
        "sewing_daily_reports",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sewing_daily_reports_section_no",
        "sewing_daily_reports",
        "section_no IS NULL OR section_no BETWEEN 1 AND 20",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sewing_daily_reports_section_no",
        "sewing_daily_reports",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sewing_daily_reports_section_no",
        "sewing_daily_reports",
        "section_no IS NULL OR section_no BETWEEN 1 AND 3",
    )

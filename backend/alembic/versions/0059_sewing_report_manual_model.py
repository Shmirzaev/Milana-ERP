"""add manual model identity to daily sewing reports

Revision ID: 0059_sewing_report_manual_model
Revises: 0058_numeric_batch_numbers
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0059_sewing_report_manual_model"
down_revision = "0058_numeric_batch_numbers"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sewing_daily_reports", sa.Column("manual_model_no", sa.String(length=64), nullable=True))
    op.add_column("sewing_daily_reports", sa.Column("manual_variant_no", sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column("sewing_daily_reports", "manual_variant_no")
    op.drop_column("sewing_daily_reports", "manual_model_no")

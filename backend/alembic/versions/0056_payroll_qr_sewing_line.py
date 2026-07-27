"""store sewing line on payroll QR labels

Revision ID: 0056_payroll_qr_sewing_line
Revises: 0055_delete_mistaken_po15
Create Date: 2026-07-16
"""

import sqlalchemy as sa
from alembic import op


revision = "0056_payroll_qr_sewing_line"
down_revision = "0055_delete_mistaken_po15"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payroll_qr_labels", sa.Column("sewing_flow_id", sa.Integer(), nullable=True))
    op.add_column("payroll_qr_labels", sa.Column("sewing_line_code", sa.String(length=64), nullable=True))
    op.add_column("payroll_qr_labels", sa.Column("sewing_line_name", sa.String(length=255), nullable=True))
    op.create_index("ix_payroll_qr_labels_sewing_flow_id", "payroll_qr_labels", ["sewing_flow_id"])
    op.create_foreign_key(
        "fk_payroll_qr_labels_sewing_flow_id",
        "payroll_qr_labels",
        "sewing_flows",
        ["sewing_flow_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_payroll_qr_labels_sewing_flow_id", "payroll_qr_labels", type_="foreignkey")
    op.drop_index("ix_payroll_qr_labels_sewing_flow_id", table_name="payroll_qr_labels")
    op.drop_column("payroll_qr_labels", "sewing_line_name")
    op.drop_column("payroll_qr_labels", "sewing_line_code")
    op.drop_column("payroll_qr_labels", "sewing_flow_id")

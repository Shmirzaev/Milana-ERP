"""store cutting passport on payroll QR labels

Revision ID: 0057_payroll_qr_cutting_passport
Revises: 0056_payroll_qr_sewing_line
Create Date: 2026-07-16
"""

import sqlalchemy as sa
from alembic import op


revision = "0057_payroll_qr_cutting_passport"
down_revision = "0056_payroll_qr_sewing_line"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payroll_qr_labels", sa.Column("cutting_passport_id", sa.Integer(), nullable=True))
    op.add_column("payroll_qr_labels", sa.Column("cutting_passport_no", sa.String(length=64), nullable=True))
    op.create_index("ix_payroll_qr_labels_cutting_passport_id", "payroll_qr_labels", ["cutting_passport_id"])
    op.create_index("ix_payroll_qr_labels_cutting_passport_no", "payroll_qr_labels", ["cutting_passport_no"])
    op.create_foreign_key(
        "fk_payroll_qr_labels_cutting_passport_id",
        "payroll_qr_labels",
        "cutting_passports",
        ["cutting_passport_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_payroll_qr_labels_cutting_passport_id", "payroll_qr_labels", type_="foreignkey")
    op.drop_index("ix_payroll_qr_labels_cutting_passport_no", table_name="payroll_qr_labels")
    op.drop_index("ix_payroll_qr_labels_cutting_passport_id", table_name="payroll_qr_labels")
    op.drop_column("payroll_qr_labels", "cutting_passport_no")
    op.drop_column("payroll_qr_labels", "cutting_passport_id")

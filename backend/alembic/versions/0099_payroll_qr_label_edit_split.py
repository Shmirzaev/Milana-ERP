"""support audited payroll QR label edits and splits

Revision ID: 0099_payroll_qr_edit_split
Revises: 0098_performance_indexes
"""

import sqlalchemy as sa
from alembic import op


revision = "0099_payroll_qr_edit_split"
down_revision = "0098_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_payroll_qr_labels_status", "payroll_qr_labels", type_="check")
    op.create_check_constraint(
        "ck_payroll_qr_labels_status",
        "payroll_qr_labels",
        "status IN ('available', 'scanned', 'superseded')",
    )
    op.add_column("payroll_qr_labels", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_qr_labels", sa.Column("superseded_by", sa.Integer(), nullable=True))
    op.add_column("payroll_qr_labels", sa.Column("split_from_label_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_payroll_qr_labels_superseded_by_users",
        "payroll_qr_labels",
        "users",
        ["superseded_by"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_payroll_qr_labels_split_from",
        "payroll_qr_labels",
        "payroll_qr_labels",
        ["split_from_label_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_payroll_qr_labels_split_from_label_id",
        "payroll_qr_labels",
        ["split_from_label_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_qr_labels_split_from_label_id", table_name="payroll_qr_labels")
    op.drop_constraint("fk_payroll_qr_labels_split_from", "payroll_qr_labels", type_="foreignkey")
    op.drop_constraint("fk_payroll_qr_labels_superseded_by_users", "payroll_qr_labels", type_="foreignkey")
    op.execute("UPDATE payroll_qr_labels SET split_from_label_id = NULL")
    op.execute("DELETE FROM payroll_qr_labels WHERE status = 'superseded'")
    op.drop_column("payroll_qr_labels", "split_from_label_id")
    op.drop_column("payroll_qr_labels", "superseded_by")
    op.drop_column("payroll_qr_labels", "superseded_at")
    op.drop_constraint("ck_payroll_qr_labels_status", "payroll_qr_labels", type_="check")
    op.create_check_constraint(
        "ck_payroll_qr_labels_status",
        "payroll_qr_labels",
        "status IN ('available', 'scanned')",
    )

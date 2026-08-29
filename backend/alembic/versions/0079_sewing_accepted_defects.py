"""allow sewing defects to close without replacement cutting

Revision ID: 0079_sewing_accepted_defects
Revises: 0078_finance_external_ids
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0079_sewing_accepted_defects"
down_revision: str | None = "0078_finance_external_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sewing_replacement_requests",
        sa.Column("accepted_defect_qty", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "sewing_replacement_requests",
        sa.Column("accepted_defect_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "sewing_replacement_requests",
        sa.Column("accepted_defect_by", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sewing_replacement_requests",
        sa.Column("accepted_defect_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sewing_replacements_accepted_defect_by_users",
        "sewing_replacement_requests",
        "users",
        ["accepted_defect_by"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_sewing_replacements_accepted_nonnegative",
        "sewing_replacement_requests",
        "accepted_defect_qty >= 0",
    )
    op.create_check_constraint(
        "ck_sewing_replacements_cut_accepted_lte_requested",
        "sewing_replacement_requests",
        "cut_qty + accepted_defect_qty <= requested_qty",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sewing_replacements_cut_accepted_lte_requested",
        "sewing_replacement_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_sewing_replacements_accepted_nonnegative",
        "sewing_replacement_requests",
        type_="check",
    )
    op.drop_constraint(
        "fk_sewing_replacements_accepted_defect_by_users",
        "sewing_replacement_requests",
        type_="foreignkey",
    )
    op.drop_column("sewing_replacement_requests", "accepted_defect_at")
    op.drop_column("sewing_replacement_requests", "accepted_defect_by")
    op.drop_column("sewing_replacement_requests", "accepted_defect_reason")
    op.drop_column("sewing_replacement_requests", "accepted_defect_qty")

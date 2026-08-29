"""add report-only pieces for Usluga secondary fabrics

Revision ID: 0108_usluga_report_pieces
Revises: 0107_usluga_cutting_approval
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0108_usluga_report_pieces"
down_revision = "0107_usluga_cutting_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cutting_records",
        sa.Column("report_piece_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_cutting_records_report_piece_nonnegative",
        "cutting_records",
        "report_piece_count >= 0",
    )
    op.alter_column("cutting_records", "report_piece_count", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_cutting_records_report_piece_nonnegative",
        "cutting_records",
        type_="check",
    )
    op.drop_column("cutting_records", "report_piece_count")

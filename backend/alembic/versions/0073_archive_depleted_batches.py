"""archive depleted stock batches without deleting traceability

Revision ID: 0073_archive_depleted_batches
Revises: 0072_sewing_report_sections
"""

import sqlalchemy as sa
from alembic import op


revision = "0073_archive_depleted_batches"
down_revision = "0072_sewing_report_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_batches",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("archived_by", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_stock_batches_archived_by_users",
        "stock_batches",
        "users",
        ["archived_by"],
        ["id"],
    )
    op.create_index(
        "ix_stock_batches_archived_at",
        "stock_batches",
        ["archived_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_stock_batches_archived_at", table_name="stock_batches")
    op.drop_constraint(
        "fk_stock_batches_archived_by_users",
        "stock_batches",
        type_="foreignkey",
    )
    op.drop_column("stock_batches", "archived_by")
    op.drop_column("stock_batches", "archived_at")

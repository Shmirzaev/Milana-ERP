"""Make finance integration external IDs unique.

Revision ID: 0078_finance_external_ids
Revises: 0077_cutting_passport_size_range
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0078_finance_external_ids"
down_revision: str | None = "0077_cutting_passport_size_range"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_invoices_external_source_id",
        "invoices",
        ["external_source", "external_id"],
    )
    op.create_unique_constraint(
        "uq_payments_external_source_id",
        "payments",
        ["external_source", "external_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_payments_external_source_id", "payments", type_="unique")
    op.drop_constraint("uq_invoices_external_source_id", "invoices", type_="unique")

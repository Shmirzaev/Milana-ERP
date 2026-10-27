"""Widen cutting passport size range for explicit size lists.

Revision ID: 0077_cutting_passport_size_range
Revises: 0076_cutting_beika_usage
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0077_cutting_passport_size_range"
down_revision: str | None = "0076_cutting_beika_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "cutting_passports",
        "size_range",
        existing_type=sa.String(length=32),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "cutting_passports",
        "size_range",
        existing_type=sa.String(length=255),
        type_=sa.String(length=32),
        existing_nullable=True,
    )

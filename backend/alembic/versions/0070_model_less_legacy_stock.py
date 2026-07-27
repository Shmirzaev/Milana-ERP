"""allow legacy finished-goods stock without catalog models

Revision ID: 0070_model_less_legacy_stock
Revises: 0069_legacy_finished_goods
"""

from alembic import op
import sqlalchemy as sa


revision = "0070_model_less_legacy_stock"
down_revision = "0069_legacy_finished_goods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "packages",
        "model_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "package_items",
        "model_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "finished_goods_stock",
        "model_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "finished_goods_stock",
        "model_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "package_items",
        "model_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "packages",
        "model_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

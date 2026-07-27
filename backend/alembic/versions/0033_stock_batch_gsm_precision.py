"""increase stock batch gsm precision

Revision ID: 0033_stock_batch_gsm_precision
Revises: 0032_cutting_material_usage
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa


revision = "0033_stock_batch_gsm_precision"
down_revision = "0032_cutting_material_usage"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "stock_batches" not in inspector.get_table_names():
        return

    if bind.dialect.name == "sqlite":
        return

    op.alter_column(
        "stock_batches",
        "gsm",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Numeric(14, 6),
        existing_nullable=True,
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "stock_batches" not in inspector.get_table_names():
        return

    if bind.dialect.name == "sqlite":
        return

    op.alter_column(
        "stock_batches",
        "gsm",
        existing_type=sa.Numeric(14, 6),
        type_=sa.Numeric(10, 2),
        existing_nullable=True,
    )

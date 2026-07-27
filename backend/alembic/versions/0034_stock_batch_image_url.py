"""add stock batch image url

Revision ID: 0034_stock_batch_image_url
Revises: 0033_stock_batch_gsm_precision
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0034_stock_batch_image_url"
down_revision = "0033_stock_batch_gsm_precision"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "stock_batches" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("stock_batches")}
    if "image_url" not in columns:
        op.add_column("stock_batches", sa.Column("image_url", sa.String(length=512), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "stock_batches" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("stock_batches")}
    if "image_url" in columns:
        op.drop_column("stock_batches", "image_url")

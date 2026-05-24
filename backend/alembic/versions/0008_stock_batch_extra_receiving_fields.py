"""add extra receiving fields to stock batches

Revision ID: 0008_stock_batch_fields
Revises: 0007_shipment_scan_logs
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_stock_batch_fields"
down_revision = "0007_shipment_scan_logs"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "stock_batches" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("stock_batches")}

    if "old_code" not in columns:
        op.add_column("stock_batches", sa.Column("old_code", sa.String(length=64), nullable=True))
    if "color_code" not in columns:
        op.add_column("stock_batches", sa.Column("color_code", sa.String(length=32), nullable=True))
    if "color_status" not in columns:
        op.add_column("stock_batches", sa.Column("color_status", sa.String(length=64), nullable=True))
    if "order_no" not in columns:
        op.add_column("stock_batches", sa.Column("order_no", sa.String(length=64), nullable=True))
    if "piece_count" not in columns:
        op.add_column("stock_batches", sa.Column("piece_count", sa.Integer(), nullable=True))
    if "processes" not in columns:
        op.add_column("stock_batches", sa.Column("processes", sa.String(length=255), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "stock_batches" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("stock_batches")}

    if "processes" in columns:
        op.drop_column("stock_batches", "processes")
    if "piece_count" in columns:
        op.drop_column("stock_batches", "piece_count")
    if "order_no" in columns:
        op.drop_column("stock_batches", "order_no")
    if "color_status" in columns:
        op.drop_column("stock_batches", "color_status")
    if "color_code" in columns:
        op.drop_column("stock_batches", "color_code")
    if "old_code" in columns:
        op.drop_column("stock_batches", "old_code")

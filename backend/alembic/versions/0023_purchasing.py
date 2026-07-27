"""add purchasing requests and orders

Revision ID: 0023_purchasing
Revises: 0022_user_extra_permissions
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_purchasing"
down_revision = "0022_user_extra_permissions"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "purchase_requests" not in tables:
        op.create_table(
            "purchase_requests",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("request_no", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_orders.id"), nullable=True),
            sa.Column("production_order_id", sa.Integer(), sa.ForeignKey("production_orders.id"), nullable=True),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_purchase_requests_request_no", "purchase_requests", ["request_no"], unique=True)

    if "purchase_request_lines" not in tables:
        op.create_table(
            "purchase_request_lines",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("purchase_request_id", sa.Integer(), sa.ForeignKey("purchase_requests.id"), nullable=False),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
            sa.Column("required_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("requested_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(length=32), nullable=False),
            sa.Column("available_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("shortage_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("preferred_supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_purchase_request_lines_purchase_request_id", "purchase_request_lines", ["purchase_request_id"])

    if "purchase_orders" not in tables:
        op.create_table(
            "purchase_orders",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("po_no", sa.String(length=64), nullable=False),
            sa.Column("purchase_request_id", sa.Integer(), sa.ForeignKey("purchase_requests.id"), nullable=True),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("ordered_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("expected_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_purchase_orders_po_no", "purchase_orders", ["po_no"], unique=True)

    if "purchase_order_lines" not in tables:
        op.create_table(
            "purchase_order_lines",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
            sa.Column("ordered_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("received_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(length=32), nullable=False),
            sa.Column("unit_cost", sa.Numeric(12, 4), nullable=False, server_default="0"),
            sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_purchase_order_lines_purchase_order_id", "purchase_order_lines", ["purchase_order_id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "purchase_order_lines" in tables:
        op.drop_index("ix_purchase_order_lines_purchase_order_id", table_name="purchase_order_lines")
        op.drop_table("purchase_order_lines")
    if "purchase_orders" in tables:
        op.drop_index("ix_purchase_orders_po_no", table_name="purchase_orders")
        op.drop_table("purchase_orders")
    if "purchase_request_lines" in tables:
        op.drop_index("ix_purchase_request_lines_purchase_request_id", table_name="purchase_request_lines")
        op.drop_table("purchase_request_lines")
    if "purchase_requests" in tables:
        op.drop_index("ix_purchase_requests_request_no", table_name="purchase_requests")
        op.drop_table("purchase_requests")

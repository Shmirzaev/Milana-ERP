"""allow sales lines to reference model-less legacy stock

Revision ID: 0071_model_less_legacy_sales
Revises: 0070_model_less_legacy_stock
"""

from alembic import op
import sqlalchemy as sa


revision = "0071_model_less_legacy_sales"
down_revision = "0070_model_less_legacy_stock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sales_order_items",
        "model_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column(
        "sales_order_items",
        sa.Column("finished_goods_stock_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sales_order_items",
        sa.Column("source_model_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "sales_order_items",
        sa.Column("source_model_name", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_order_items_finished_goods_stock_id",
        "sales_order_items",
        "finished_goods_stock",
        ["finished_goods_stock_id"],
        ["id"],
    )
    op.create_index(
        "ix_sales_order_items_finished_goods_stock_id",
        "sales_order_items",
        ["finished_goods_stock_id"],
    )
    op.create_check_constraint(
        "ck_sales_order_items_product_reference",
        "sales_order_items",
        "model_id IS NOT NULL OR finished_goods_stock_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sales_order_items_product_reference",
        "sales_order_items",
        type_="check",
    )
    op.drop_index(
        "ix_sales_order_items_finished_goods_stock_id",
        table_name="sales_order_items",
    )
    op.drop_constraint(
        "fk_sales_order_items_finished_goods_stock_id",
        "sales_order_items",
        type_="foreignkey",
    )
    op.drop_column("sales_order_items", "source_model_name")
    op.drop_column("sales_order_items", "source_model_code")
    op.drop_column("sales_order_items", "finished_goods_stock_id")
    op.alter_column(
        "sales_order_items",
        "model_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

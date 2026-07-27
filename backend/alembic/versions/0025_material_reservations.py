"""add material reservations

Revision ID: 0025_material_reservations
Revises: 0024_payroll
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_material_reservations"
down_revision = "0024_payroll"
branch_labels = None
depends_on = None


def _create_index_if_missing(inspector, name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if name not in indexes:
        op.create_index(name, table_name, columns, unique=unique)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "material_reservations" not in tables:
        op.create_table(
            "material_reservations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("reservation_no", sa.String(length=64), nullable=False),
            sa.Column("production_order_id", sa.Integer(), sa.ForeignKey("production_orders.id"), nullable=False),
            sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_orders.id"), nullable=True),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
            sa.Column("stock_batch_id", sa.Integer(), sa.ForeignKey("stock_batches.id"), nullable=True),
            sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=True),
            sa.Column("reserved_quantity", sa.Numeric(14, 4), nullable=False),
            sa.Column("consumed_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("released_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="reserved"),
            sa.Column("reservation_type", sa.String(length=32), nullable=False, server_default="material"),
            sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("reserved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reserved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.CheckConstraint("reserved_quantity > 0", name="ck_material_reservations_reserved_positive"),
            sa.CheckConstraint("consumed_quantity >= 0", name="ck_material_reservations_consumed_nonnegative"),
            sa.CheckConstraint("released_quantity >= 0", name="ck_material_reservations_released_nonnegative"),
            sa.CheckConstraint(
                "consumed_quantity + released_quantity <= reserved_quantity",
                name="ck_material_reservations_consumed_released_lte_reserved",
            ),
            sa.UniqueConstraint("reservation_no", name="uq_material_reservations_reservation_no"),
        )

    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, "ix_material_reservations_reservation_no", "material_reservations", ["reservation_no"], unique=True)
    _create_index_if_missing(inspector, "ix_material_reservations_production_order_id", "material_reservations", ["production_order_id"])
    _create_index_if_missing(inspector, "ix_material_reservations_sales_order_id", "material_reservations", ["sales_order_id"])
    _create_index_if_missing(inspector, "ix_material_reservations_item_id", "material_reservations", ["item_id"])
    _create_index_if_missing(inspector, "ix_material_reservations_stock_batch_id", "material_reservations", ["stock_batch_id"])
    _create_index_if_missing(inspector, "ix_material_reservations_warehouse_id", "material_reservations", ["warehouse_id"])
    _create_index_if_missing(inspector, "ix_material_reservations_status", "material_reservations", ["status"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "material_reservations" in set(inspector.get_table_names()):
        op.drop_table("material_reservations")

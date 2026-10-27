"""Add planned production materials and actual cutting material usage.

Revision ID: 0075_multi_fabric_cutting
Revises: 0074_cutting_nastilchi
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0075_multi_fabric_cutting"
down_revision: str | None = "0074_cutting_nastilchi"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "production_order_materials",
        sa.Column("production_order_id", sa.Integer(), nullable=False),
        sa.Column("stock_batch_id", sa.Integer(), nullable=False),
        sa.Column("estimated_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "estimated_quantity > 0",
            name="ck_production_order_materials_quantity_positive",
        ),
        sa.CheckConstraint(
            "position > 0",
            name="ck_production_order_materials_position_positive",
        ),
        sa.ForeignKeyConstraint(
            ["production_order_id"], ["production_orders.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["stock_batch_id"], ["stock_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "production_order_id", "stock_batch_id",
            name="uq_production_order_materials_order_batch",
        ),
        sa.UniqueConstraint(
            "production_order_id", "position",
            name="uq_production_order_materials_order_position",
        ),
    )
    op.create_index(
        op.f("ix_production_order_materials_production_order_id"),
        "production_order_materials",
        ["production_order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_production_order_materials_stock_batch_id"),
        "production_order_materials",
        ["stock_batch_id"],
        unique=False,
    )

    op.create_table(
        "cutting_material_usages",
        sa.Column("cutting_record_id", sa.Integer(), nullable=False),
        sa.Column("stock_batch_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_cutting_material_usages_quantity_positive",
        ),
        sa.CheckConstraint(
            "position > 0",
            name="ck_cutting_material_usages_position_positive",
        ),
        sa.ForeignKeyConstraint(
            ["cutting_record_id"], ["cutting_records.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["stock_batch_id"], ["stock_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cutting_record_id", "stock_batch_id",
            name="uq_cutting_material_usages_record_batch",
        ),
        sa.UniqueConstraint(
            "cutting_record_id", "position",
            name="uq_cutting_material_usages_record_position",
        ),
    )
    op.create_index(
        op.f("ix_cutting_material_usages_cutting_record_id"),
        "cutting_material_usages",
        ["cutting_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cutting_material_usages_stock_batch_id"),
        "cutting_material_usages",
        ["stock_batch_id"],
        unique=False,
    )

    # Preserve legacy production orders on the existing single-fabric path.
    # New orders explicitly populate production_order_materials; automatically
    # converting old estimates would change their BOM-based reservation totals.
    op.execute(
        """
        INSERT INTO cutting_material_usages (
            cutting_record_id, stock_batch_id, quantity, unit, position,
            created_at, updated_at
        )
        SELECT
            cr.id,
            cr.fabric_batch_id,
            cr.input_quantity,
            COALESCE(NULLIF(cr.input_unit, ''), NULLIF(sb.unit, ''), 'kg'),
            1,
            COALESCE(cr.created_at, CURRENT_TIMESTAMP),
            COALESCE(cr.updated_at, CURRENT_TIMESTAMP)
        FROM cutting_records cr
        JOIN stock_batches sb ON sb.id = cr.fabric_batch_id
        WHERE cr.fabric_batch_id IS NOT NULL
          AND cr.input_quantity > 0
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_cutting_material_usages_stock_batch_id"),
        table_name="cutting_material_usages",
    )
    op.drop_index(
        op.f("ix_cutting_material_usages_cutting_record_id"),
        table_name="cutting_material_usages",
    )
    op.drop_table("cutting_material_usages")
    op.drop_index(
        op.f("ix_production_order_materials_stock_batch_id"),
        table_name="production_order_materials",
    )
    op.drop_index(
        op.f("ix_production_order_materials_production_order_id"),
        table_name="production_order_materials",
    )
    op.drop_table("production_order_materials")

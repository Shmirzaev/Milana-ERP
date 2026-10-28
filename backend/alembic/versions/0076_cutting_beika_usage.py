"""Add exact inventory batch usage for cutting Beyka material.

Revision ID: 0076_cutting_beika_usage
Revises: 0075_multi_fabric_cutting
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0076_cutting_beika_usage"
down_revision: str | None = "0075_multi_fabric_cutting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cutting_beika_material_usages",
        sa.Column("cutting_record_id", sa.Integer(), nullable=False),
        sa.Column("stock_batch_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit", sa.String(length=32), server_default="kg", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_cutting_beika_material_usages_quantity_positive",
        ),
        sa.CheckConstraint(
            "position > 0",
            name="ck_cutting_beika_material_usages_position_positive",
        ),
        sa.ForeignKeyConstraint(
            ["cutting_record_id"], ["cutting_records.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["stock_batch_id"], ["stock_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cutting_record_id", "stock_batch_id",
            name="uq_cutting_beika_material_usages_record_batch",
        ),
        sa.UniqueConstraint(
            "cutting_record_id", "position",
            name="uq_cutting_beika_material_usages_record_position",
        ),
    )
    op.create_index(
        op.f("ix_cutting_beika_material_usages_cutting_record_id"),
        "cutting_beika_material_usages",
        ["cutting_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cutting_beika_material_usages_stock_batch_id"),
        "cutting_beika_material_usages",
        ["stock_batch_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_cutting_beika_material_usages_stock_batch_id"),
        table_name="cutting_beika_material_usages",
    )
    op.drop_index(
        op.f("ix_cutting_beika_material_usages_cutting_record_id"),
        table_name="cutting_beika_material_usages",
    )
    op.drop_table("cutting_beika_material_usages")

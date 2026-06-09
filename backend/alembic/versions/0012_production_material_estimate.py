"""add production material estimate fields

Revision ID: 0012_material_estimate
Revises: 0011_model_image_type
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_material_estimate"
down_revision = "0011_model_image_type"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "production_orders" not in tables:
        return

    if not _has_column(inspector, "production_orders", "estimated_material_code"):
        op.add_column("production_orders", sa.Column("estimated_material_code", sa.String(length=128), nullable=True))
    if not _has_column(inspector, "production_orders", "estimated_material_amount"):
        op.add_column("production_orders", sa.Column("estimated_material_amount", sa.Numeric(14, 4), nullable=True))
    if not _has_column(inspector, "production_orders", "estimated_material_unit"):
        op.add_column("production_orders", sa.Column("estimated_material_unit", sa.String(length=32), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "production_orders" not in tables:
        return

    for name in ["estimated_material_unit", "estimated_material_amount", "estimated_material_code"]:
        if _has_column(inspector, "production_orders", name):
            op.drop_column("production_orders", name)

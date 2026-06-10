"""add cutting passport excel fallback fields

Revision ID: 0013_cutting_passport_excel
Revises: 0012_material_estimate
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_cutting_passport_excel"
down_revision = "0012_material_estimate"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "cutting_passports" not in tables:
        return

    additions = [
        ("model_code", sa.Column("model_code", sa.String(length=128), nullable=True)),
        ("image_ref", sa.Column("image_ref", sa.String(length=512), nullable=True)),
        ("operator_name_manual", sa.Column("operator_name_manual", sa.String(length=128), nullable=True)),
        ("order_no", sa.Column("order_no", sa.String(length=128), nullable=True)),
    ]
    for name, column in additions:
        if not _has_column(inspector, "cutting_passports", name):
            op.add_column("cutting_passports", column)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "cutting_passports" not in tables:
        return

    for name in ["order_no", "operator_name_manual", "image_ref", "model_code"]:
        if _has_column(inspector, "cutting_passports", name):
            op.drop_column("cutting_passports", name)

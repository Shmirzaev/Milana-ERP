"""add cutting material usage fields

Revision ID: 0032_cutting_material_usage
Revises: 0031_item_image_url
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0032_cutting_material_usage"
down_revision = "0031_item_image_url"
branch_labels = None
depends_on = None


def _has_check(inspector, table_name: str, name: str) -> bool:
    return any(check.get("name") == name for check in inspector.get_check_constraints(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cutting_records" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("cutting_records")}
    for name in ("layer_material_kg", "beika_kg", "material_rolls_used"):
        if name not in columns:
            op.add_column(
                "cutting_records",
                sa.Column(name, sa.Numeric(14, 4), nullable=False, server_default="0"),
            )

    if bind.dialect.name == "sqlite":
        return

    inspector = sa.inspect(bind)
    checks = [
        ("ck_cutting_records_layer_material_nonnegative", "layer_material_kg >= 0"),
        ("ck_cutting_records_beika_nonnegative", "beika_kg >= 0"),
        ("ck_cutting_records_rolls_nonnegative", "material_rolls_used >= 0"),
    ]
    for name, condition in checks:
        if not _has_check(inspector, "cutting_records", name):
            op.create_check_constraint(name, "cutting_records", condition)
            inspector = sa.inspect(bind)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cutting_records" not in inspector.get_table_names():
        return

    if bind.dialect.name != "sqlite":
        inspector = sa.inspect(bind)
        for name in (
            "ck_cutting_records_rolls_nonnegative",
            "ck_cutting_records_beika_nonnegative",
            "ck_cutting_records_layer_material_nonnegative",
        ):
            if _has_check(inspector, "cutting_records", name):
                op.drop_constraint(name, "cutting_records", type_="check")
                inspector = sa.inspect(bind)

    columns = {column["name"] for column in sa.inspect(bind).get_columns("cutting_records")}
    for name in ("material_rolls_used", "beika_kg", "layer_material_kg"):
        if name in columns:
            op.drop_column("cutting_records", name)

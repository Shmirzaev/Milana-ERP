"""allow inventory-independent fabric names for Usluga model BOM rows

Revision ID: 0106_usluga_manual_fabric
Revises: 0105_eco_usluga_attendance
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0106_usluga_manual_fabric"
down_revision = "0105_eco_usluga_attendance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_bom", sa.Column("material_name", sa.String(length=255), nullable=True))
    op.alter_column("model_bom", "item_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "ck_model_bom_item_or_manual_material",
        "model_bom",
        "(item_id IS NOT NULL AND material_name IS NULL) OR "
        "(item_id IS NULL AND material_name IS NOT NULL AND btrim(material_name) <> '')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    manual_rows = connection.execute(
        sa.text("SELECT count(*) FROM model_bom WHERE item_id IS NULL")
    ).scalar_one()
    if manual_rows:
        raise RuntimeError(
            "Cannot downgrade while inventory-independent Usluga fabric rows exist; "
            "remove or relink them first."
        )
    op.drop_constraint("ck_model_bom_item_or_manual_material", "model_bom", type_="check")
    op.alter_column("model_bom", "item_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("model_bom", "material_name")

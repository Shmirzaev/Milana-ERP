"""remove generic pictures from model fabric rows

Revision ID: 0064_remove_fabric_pictures
Revises: 0063_variant_material_pictures
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0064_remove_fabric_pictures"
down_revision = "0063_variant_material_pictures"
branch_labels = None
depends_on = None


def upgrade():
    # Generic inventory-master pictures were copied into model fabric BOM rows.
    # Remove only those exact copies; restored legacy batch pictures and custom
    # variant uploads have different paths and remain untouched.
    op.get_bind().execute(sa.text("""
        UPDATE model_bom AS mb
        SET photo_url = NULL
        FROM items AS i
        WHERE i.id = mb.item_id
          AND i.category IN ('fabric', 'semi_finished')
          AND i.image_url IS NOT NULL
          AND mb.photo_url = i.image_url
    """))


def downgrade():
    # Do not recreate automatically copied pictures on rollback.
    pass

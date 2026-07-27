"""restore legacy variant material pictures

Revision ID: 0063_variant_material_pictures
Revises: 0062_planning_fabric_batch
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0063_variant_material_pictures"
down_revision = "0062_planning_fabric_batch"
branch_labels = None
depends_on = None


def upgrade():
    # Migration 0062 removed physical batch links from model BOM rows, as
    # intended, but some legacy material pictures lived only on those batches.
    # Recover the picture by the retained master fabric + color. Preserve any
    # custom picture that differs from the generic inventory master image.
    op.get_bind().execute(sa.text("""
        UPDATE model_bom AS mb
        SET photo_url = (
            SELECT sb.image_url
            FROM stock_batches AS sb
            WHERE sb.item_id = mb.item_id
              AND sb.image_url IS NOT NULL
              AND lower(trim(coalesce(sb.color, ''))) = lower(trim(coalesce(mb.color, '')))
            ORDER BY sb.received_date DESC, sb.id DESC
            LIMIT 1
        )
        FROM items AS i
        WHERE i.id = mb.item_id
          AND i.category IN ('fabric', 'semi_finished')
          AND nullif(trim(coalesce(mb.color, '')), '') IS NOT NULL
          AND (mb.photo_url IS NULL OR mb.photo_url = i.image_url)
          AND EXISTS (
              SELECT 1
              FROM stock_batches AS sb
              WHERE sb.item_id = mb.item_id
                AND sb.image_url IS NOT NULL
                AND lower(trim(coalesce(sb.color, ''))) = lower(trim(coalesce(mb.color, '')))
          )
    """))


def downgrade():
    # Recovered image references are valid model data and are intentionally
    # retained if the application revision is rolled back.
    pass

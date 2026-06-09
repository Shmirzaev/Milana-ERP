"""add model image type

Revision ID: 0011_model_image_type
Revises: 0010_settings_model_fields
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_model_image_type"
down_revision = "0010_settings_model_fields"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "model_images" in tables and not _has_column(inspector, "model_images", "image_type"):
        op.add_column("model_images", sa.Column("image_type", sa.String(length=32), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "model_images" in tables and _has_column(inspector, "model_images", "image_type"):
        op.drop_column("model_images", "image_type")

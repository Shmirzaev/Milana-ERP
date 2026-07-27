"""add item image url

Revision ID: 0031_item_image_url
Revises: 0030_model_bom_photo_url
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0031_item_image_url"
down_revision = "0030_model_bom_photo_url"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("items")}
    if "image_url" not in columns:
        op.add_column("items", sa.Column("image_url", sa.String(length=512), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("items")}
    if "image_url" in columns:
        op.drop_column("items", "image_url")

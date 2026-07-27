"""add model bom photo url

Revision ID: 0030_model_bom_photo_url
Revises: 0029_item_composition_json
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0030_model_bom_photo_url"
down_revision = "0029_item_composition_json"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "model_bom" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("model_bom")}
    if "photo_url" not in columns:
        op.add_column("model_bom", sa.Column("photo_url", sa.String(length=512), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "model_bom" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("model_bom")}
    if "photo_url" in columns:
        op.drop_column("model_bom", "photo_url")

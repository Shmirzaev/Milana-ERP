"""store uploaded model image bytes

Revision ID: 0020_model_image_file_data
Revises: 0019_bundle_batch_link
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa


revision = "0020_model_image_file_data"
down_revision = "0019_bundle_batch_link"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "model_images" in tables and not _has_column(inspector, "model_images", "file_data"):
        op.add_column("model_images", sa.Column("file_data", sa.LargeBinary(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "model_images" in tables and _has_column(inspector, "model_images", "file_data"):
        op.drop_column("model_images", "file_data")

"""add stock batch link to model bom

Revision ID: 0035_model_bom_stock_batch
Revises: 0034_stock_batch_image_url
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0035_model_bom_stock_batch"
down_revision = "0034_stock_batch_image_url"
branch_labels = None
depends_on = None


def _fk_exists(inspector, table_name: str, constraint_name: str) -> bool:
    return any(fk.get("name") == constraint_name for fk in inspector.get_foreign_keys(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "model_bom" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("model_bom")}
    if "stock_batch_id" not in columns:
        op.add_column("model_bom", sa.Column("stock_batch_id", sa.Integer(), nullable=True))
    if "stock_batches" in tables and not _fk_exists(inspector, "model_bom", "fk_model_bom_stock_batch_id_stock_batches"):
        op.create_foreign_key(
            "fk_model_bom_stock_batch_id_stock_batches",
            "model_bom",
            "stock_batches",
            ["stock_batch_id"],
            ["id"],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "model_bom" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("model_bom")}
    if "stock_batch_id" not in columns:
        return
    if _fk_exists(inspector, "model_bom", "fk_model_bom_stock_batch_id_stock_batches"):
        op.drop_constraint("fk_model_bom_stock_batch_id_stock_batches", "model_bom", type_="foreignkey")
    op.drop_column("model_bom", "stock_batch_id")

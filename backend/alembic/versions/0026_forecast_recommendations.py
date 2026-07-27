"""add forecast recommendations

Revision ID: 0026_forecast_recommendations
Revises: 0025_material_reservations
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0026_forecast_recommendations"
down_revision = "0025_material_reservations"
branch_labels = None
depends_on = None


def _create_index_if_missing(inspector, name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if name not in indexes:
        op.create_index(name, table_name, columns, unique=unique)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "forecast_recommendations" not in tables:
        op.create_table(
            "forecast_recommendations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("recommendation_type", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
            sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=True),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=True),
            sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=True),
            sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id"), nullable=True),
            sa.Column("color", sa.String(length=64), nullable=True),
            sa.Column("size", sa.String(length=32), nullable=True),
            sa.Column("suggested_quantity", sa.Numeric(14, 4), nullable=False),
            sa.Column("unit", sa.String(length=32), nullable=True),
            sa.Column("confidence", sa.String(length=16), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("source_json", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )

    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, "ix_forecast_recommendations_recommendation_type", "forecast_recommendations", ["recommendation_type"])
    _create_index_if_missing(inspector, "ix_forecast_recommendations_status", "forecast_recommendations", ["status"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "forecast_recommendations" in set(inspector.get_table_names()):
        op.drop_table("forecast_recommendations")

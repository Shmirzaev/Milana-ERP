"""add package weight in kg

Revision ID: 0015_package_weight_kg
Revises: 0014_bundle_sewing_factory_code
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_package_weight_kg"
down_revision = "0014_bundle_sewing_factory_code"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("packages")}
    if "weight_kg" not in columns:
        op.add_column("packages", sa.Column("weight_kg", sa.Numeric(14, 4), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("packages")}
    if "weight_kg" in columns:
        op.drop_column("packages", "weight_kg")

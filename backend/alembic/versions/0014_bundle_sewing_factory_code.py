"""add selected sewing factory to bundles

Revision ID: 0014_bundle_sewing_factory_code
Revises: 0013_cutting_passport_excel
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_bundle_sewing_factory_code"
down_revision = "0013_cutting_passport_excel"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("bundles")}
    if "sewing_factory_code" not in columns:
        op.add_column("bundles", sa.Column("sewing_factory_code", sa.String(length=32), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("bundles")}
    if "sewing_factory_code" in columns:
        op.drop_column("bundles", "sewing_factory_code")

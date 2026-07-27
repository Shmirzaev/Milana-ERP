"""add per-user extra permissions

Revision ID: 0022_user_extra_permissions
Revises: 0021_order_number_backfill
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_user_extra_permissions"
down_revision = "0021_order_number_backfill"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" in tables and not _has_column(inspector, "users", "extra_permissions"):
        op.add_column(
            "users",
            sa.Column("extra_permissions", sa.JSON(), nullable=False, server_default="[]"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" in tables and _has_column(inspector, "users", "extra_permissions"):
        op.drop_column("users", "extra_permissions")

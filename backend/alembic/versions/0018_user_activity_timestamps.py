"""add user activity timestamps

Revision ID: 0018_user_activity_timestamps
Revises: 0017_package_change_requests
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_user_activity_timestamps"
down_revision = "0017_package_change_requests"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "last_login_at" not in columns:
        op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    if "last_seen_at" not in columns:
        op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "last_seen_at" in columns:
        op.drop_column("users", "last_seen_at")
    if "last_login_at" in columns:
        op.drop_column("users", "last_login_at")

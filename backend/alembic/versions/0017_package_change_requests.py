"""add package change requests

Revision ID: 0017_package_change_requests
Revises: 0016_package_batch_allocations
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_package_change_requests"
down_revision = "0016_package_batch_allocations"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "package_change_requests" not in inspector.get_table_names():
        op.create_table(
            "package_change_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("package_id", sa.Integer(), nullable=False),
            sa.Column("package_no", sa.String(length=64), nullable=False),
            sa.Column("request_type", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("before_json", sa.JSON(), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_notes", sa.Text(), nullable=True),
        )
    indexes = {idx["name"] for idx in inspector.get_indexes("package_change_requests")}
    if "ix_package_change_requests_package_id" not in indexes:
        op.create_index("ix_package_change_requests_package_id", "package_change_requests", ["package_id"])
    if "ix_package_change_requests_package_no" not in indexes:
        op.create_index("ix_package_change_requests_package_no", "package_change_requests", ["package_no"])
    if "ix_package_change_requests_status" not in indexes:
        op.create_index("ix_package_change_requests_status", "package_change_requests", ["status"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "package_change_requests" in inspector.get_table_names():
        op.drop_table("package_change_requests")

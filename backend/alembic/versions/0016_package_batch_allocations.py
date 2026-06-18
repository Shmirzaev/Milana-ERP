"""add package batch allocations

Revision ID: 0016_package_batch_allocations
Revises: 0015_package_weight_kg
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_package_batch_allocations"
down_revision = "0015_package_weight_kg"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "package_batch_allocations" not in inspector.get_table_names():
        op.create_table(
            "package_batch_allocations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("package_id", sa.Integer(), sa.ForeignKey("packages.id"), nullable=False),
            sa.Column("production_batch_id", sa.Integer(), sa.ForeignKey("production_batches.id"), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
        )
    indexes = {idx["name"] for idx in inspector.get_indexes("package_batch_allocations")}
    if "ix_package_batch_allocations_package_id" not in indexes:
        op.create_index("ix_package_batch_allocations_package_id", "package_batch_allocations", ["package_id"])
    if "ix_package_batch_allocations_production_batch_id" not in indexes:
        op.create_index("ix_package_batch_allocations_production_batch_id", "package_batch_allocations", ["production_batch_id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "package_batch_allocations" in inspector.get_table_names():
        op.drop_table("package_batch_allocations")

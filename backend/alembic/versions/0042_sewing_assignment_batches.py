"""add production batch to sewing assignments

Revision ID: 0042_sewing_assignment_batches
Revises: 0041_production_printing_details
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa


revision = "0042_sewing_assignment_batches"
down_revision = "0041_production_printing_details"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c.get("name") for c in inspector.get_columns("sewing_assignments")}
    if "production_batch_id" not in columns:
        op.add_column(
            "sewing_assignments",
            sa.Column("production_batch_id", sa.Integer(), sa.ForeignKey("production_batches.id"), nullable=True),
        )
    indexes = {idx.get("name") for idx in inspector.get_indexes("sewing_assignments")}
    if "ix_sewing_assignments_production_batch_id" not in indexes:
        op.create_index(
            "ix_sewing_assignments_production_batch_id",
            "sewing_assignments",
            ["production_batch_id"],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {idx.get("name") for idx in inspector.get_indexes("sewing_assignments")}
    if "ix_sewing_assignments_production_batch_id" in indexes:
        op.drop_index("ix_sewing_assignments_production_batch_id", table_name="sewing_assignments")
    columns = {c.get("name") for c in inspector.get_columns("sewing_assignments")}
    if "production_batch_id" in columns:
        op.drop_column("sewing_assignments", "production_batch_id")

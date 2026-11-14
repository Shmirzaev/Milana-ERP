"""Store exact source item attribution; historical allocations remain unknown.

Revision ID: 0157_package_allocation_items
Revises: 0156_variant_price_workflow
"""
from alembic import op
import sqlalchemy as sa

revision = "0157_package_allocation_items"
down_revision = "0156_variant_price_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("package_batch_allocations", sa.Column("item_breakdown", sa.JSON(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text(
            "SELECT 1 FROM package_batch_allocations WHERE item_breakdown IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Exact package source evidence exists; downgrade would discard traceability")
    op.drop_column("package_batch_allocations", "item_breakdown")

"""add bounded model lookup index

Revision ID: 0097_model_lookup_indexes
Revises: 0096_batch_item_consistency
"""

from alembic import op


revision = "0097_model_lookup_indexes"
down_revision = "0096_batch_item_consistency"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_models_legacy_status_created_id"


def upgrade() -> None:
    # This index supports the status-filtered list and selector order while the
    # existing 0084 index continues to serve model-family/variant lookup.
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '10s'")
        op.execute("SET statement_timeout = '5min'")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY {INDEX_NAME} "
            "ON models (is_legacy_import, status, created_at DESC, id DESC)"
        )
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '10s'")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
        op.execute("RESET lock_timeout")

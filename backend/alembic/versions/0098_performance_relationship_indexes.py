"""add measured relationship and workflow indexes

Revision ID: 0098_performance_indexes
Revises: 0097_model_lookup_indexes
"""

from alembic import op


revision = "0098_performance_indexes"
down_revision = "0097_model_lookup_indexes"
branch_labels = None
depends_on = None


INDEXES = {
    "ix_model_images_model_id_id": "model_images (model_id, id DESC)",
    "ix_model_sizes_model_id_id": "model_sizes (model_id, id DESC)",
    "ix_model_colors_model_id_id": "model_colors (model_id, id DESC)",
    "ix_model_bom_model_id_id": "model_bom (model_id, id DESC)",
    "ix_cutting_records_work_order_batch": "cutting_records (work_order_id, production_batch_id)",
    "ix_printing_records_work_order_batch": "printing_records (work_order_id, production_batch_id)",
    "ix_sewing_records_work_order_batch": "sewing_records (work_order_id, production_batch_id)",
    "ix_packaging_records_work_order_batch": "packaging_records (work_order_id, production_batch_id)",
    "ix_packages_order_status_batch": "packages (production_order_id, status, production_batch_id)",
    "ix_finished_goods_model_status_id": "finished_goods_stock (model_id, status, id DESC)",
    "ix_finished_goods_package_id": "finished_goods_stock (package_id)",
}


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY keeps production writes available. Alembic's
    # autocommit block is required because PostgreSQL rejects CONCURRENTLY in a
    # transaction block.
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '10s'")
        op.execute("SET statement_timeout = '5min'")
        for name, definition in INDEXES.items():
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {definition}")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notifications_user_unread_id "
            "ON notifications (user_id, id DESC) WHERE is_read = false"
        )
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '10s'")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_notifications_user_unread_id")
        for name in reversed(tuple(INDEXES)):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        op.execute("RESET lock_timeout")

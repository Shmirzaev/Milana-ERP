"""store purchase receipt internal batch numbers

Revision ID: 0103_purchase_internal_batch
Revises: 0102_attendance_mirror
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0103_purchase_internal_batch"
down_revision = "0102_attendance_mirror"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_batches",
        sa.Column("internal_batch_no", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_stock_batches_internal_batch_no",
        "stock_batches",
        ["internal_batch_no"],
    )
    op.execute(
        """
        UPDATE stock_batches AS batch
        SET internal_batch_no = purchase_order.po_no
        FROM stock_movements AS movement
        JOIN purchase_order_lines AS purchase_line
          ON purchase_line.id = movement.reference_id
        JOIN purchase_orders AS purchase_order
          ON purchase_order.id = purchase_line.purchase_order_id
        WHERE movement.batch_id = batch.id
          AND movement.movement_type = 'receive'
          AND movement.reference_type = 'PurchaseOrderLine'
          AND batch.internal_batch_no IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_stock_batches_internal_batch_no", table_name="stock_batches")
    op.drop_column("stock_batches", "internal_batch_no")

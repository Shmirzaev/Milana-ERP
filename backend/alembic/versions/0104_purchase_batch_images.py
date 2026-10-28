"""backfill purchase receipt batch pictures

Revision ID: 0104_purchase_batch_images
Revises: 0103_purchase_internal_batch
Create Date: 2026-08-19
"""

from alembic import op


revision = "0104_purchase_batch_images"
down_revision = "0103_purchase_internal_batch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE stock_batches AS batch
        SET image_url = purchase_line.photo_url
        FROM stock_movements AS movement
        JOIN purchase_order_lines AS purchase_line
          ON purchase_line.id = movement.reference_id
        WHERE movement.batch_id = batch.id
          AND movement.movement_type = 'receive'
          AND movement.reference_type = 'PurchaseOrderLine'
          AND (batch.image_url IS NULL OR btrim(batch.image_url) = '')
          AND purchase_line.photo_url IS NOT NULL
          AND btrim(purchase_line.photo_url) <> ''
        """
    )


def downgrade() -> None:
    # This migration fills missing pictures from their authoritative purchase
    # lines. A downgrade must not erase a picture that may since be in use.
    pass

"""reset zero-quantity storage transfer work orders

Revision ID: 0036_reset_zero_storage_transfer
Revises: 0035_model_bom_stock_batch
Create Date: 2026-07-08
"""
from alembic import op


revision = "0036_reset_zero_storage_transfer"
down_revision = "0035_model_bom_stock_batch"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE work_orders wo
        SET
            status = 'waiting',
            start_time = NULL,
            end_time = NULL,
            actual_input_qty = 0,
            actual_output_qty = 0,
            passed_qty = 0,
            failed_qty = 0,
            rework_qty = 0
        WHERE wo.operation = 'storage_transfer'
          AND wo.status IN ('in_progress', 'pending', 'collected', 'ready', 'paused')
          AND COALESCE(wo.actual_output_qty, 0) = 0
          AND COALESCE(wo.passed_qty, 0) = 0
          AND COALESCE(wo.failed_qty, 0) = 0
          AND COALESCE(wo.rework_qty, 0) = 0
          AND NOT EXISTS (
              SELECT 1
              FROM packages p
              WHERE p.production_order_id = wo.production_order_id
                AND p.status IN ('received_in_storage', 'reserved', 'shipped', 'delivered')
          )
        """
    )
    op.execute(
        """
        UPDATE production_orders po
        SET status = 'cutting'
        WHERE po.status = 'storage_transfer'
          AND EXISTS (
              SELECT 1
              FROM work_orders cut
              WHERE cut.production_order_id = po.id
                AND cut.operation = 'cutting'
                AND (
                    cut.status IN ('in_progress', 'pending', 'collected', 'ready', 'paused')
                    OR COALESCE(cut.actual_output_qty, 0) > 0
                    OR COALESCE(cut.passed_qty, 0) > 0
                    OR COALESCE(cut.failed_qty, 0) > 0
                    OR COALESCE(cut.rework_qty, 0) > 0
                )
          )
          AND NOT EXISTS (
              SELECT 1
              FROM packages p
              WHERE p.production_order_id = po.id
                AND p.status IN ('received_in_storage', 'reserved', 'shipped', 'delivered')
          )
        """
    )


def downgrade():
    pass

"""lift downstream plans from cutting output

Revision ID: 0038_lift_downstream_plans
Revises: 0037_limit_default_sewing_flows
Create Date: 2026-07-08
"""
from alembic import op


revision = "0038_lift_downstream_plans"
down_revision = "0037_limit_default_sewing_flows"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        WITH cutting_output AS (
            SELECT
                w.id AS work_order_id,
                w.production_order_id,
                w.production_batch_id,
                GREATEST(
                    COALESCE(w.actual_output_qty, 0),
                    COALESCE(w.passed_qty, 0),
                    COALESCE(cr.total_bundled_qty, 0),
                    CASE
                        WHEN w.production_batch_id IS NULL THEN COALESCE(b_order.bundle_qty, 0)
                        ELSE COALESCE(b_batch.bundle_qty, 0)
                    END
                ) AS output_qty
            FROM work_orders w
            LEFT JOIN (
                SELECT
                    work_order_id,
                    COALESCE(SUM(total_bundled_quantity), 0) AS total_bundled_qty
                FROM cutting_records
                GROUP BY work_order_id
            ) cr ON cr.work_order_id = w.id
            LEFT JOIN (
                SELECT
                    production_order_id,
                    COALESCE(SUM(quantity), 0) AS bundle_qty
                FROM bundles
                GROUP BY production_order_id
            ) b_order ON b_order.production_order_id = w.production_order_id
            LEFT JOIN (
                SELECT
                    production_order_id,
                    production_batch_id,
                    COALESCE(SUM(quantity), 0) AS bundle_qty
                FROM bundles
                WHERE production_batch_id IS NOT NULL
                GROUP BY production_order_id, production_batch_id
            ) b_batch ON b_batch.production_order_id = w.production_order_id
                AND b_batch.production_batch_id = w.production_batch_id
            WHERE w.operation = 'cutting'
        )
        UPDATE work_orders w
        SET
            planned_input_qty = GREATEST(COALESCE(w.planned_input_qty, 0), cutting_output.output_qty),
            planned_output_qty = GREATEST(COALESCE(w.planned_output_qty, 0), cutting_output.output_qty)
        FROM cutting_output
        WHERE w.production_order_id = cutting_output.production_order_id
          AND (
              (w.production_batch_id IS NULL AND cutting_output.production_batch_id IS NULL)
              OR w.production_batch_id = cutting_output.production_batch_id
          )
          AND w.operation IN ('printing', 'sewing', 'packaging', 'storage_transfer')
          AND cutting_output.output_qty > GREATEST(COALESCE(w.planned_input_qty, 0), COALESCE(w.planned_output_qty, 0))
        """
    )


def downgrade():
    pass

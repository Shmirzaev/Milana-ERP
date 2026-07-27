"""delete mistaken production workflow PO-2026-000015

Revision ID: 0055_delete_mistaken_po15
Revises: 0054_payroll_qr_ids
Create Date: 2026-07-16
"""

from alembic import op


revision = "0055_delete_mistaken_po15"
down_revision = "0054_payroll_qr_ids"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        DECLARE
            target_id INTEGER;
        BEGIN
            SELECT id
            INTO target_id
            FROM production_orders
            WHERE production_no = 'PO-2026-000015'
            FOR UPDATE;

            IF target_id IS NULL THEN
                RAISE NOTICE 'PO-2026-000015 is already absent';
                RETURN;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM work_orders
                WHERE production_order_id = target_id
                  AND (
                      status <> 'waiting'
                      OR actual_input_qty <> 0
                      OR actual_output_qty <> 0
                      OR passed_qty <> 0
                      OR failed_qty <> 0
                      OR rework_qty <> 0
                  )
            ) THEN
                RAISE EXCEPTION
                    'Refusing to delete PO-2026-000015 because production activity now exists';
            END IF;

            DELETE FROM work_orders
            WHERE production_order_id = target_id;

            DELETE FROM production_order_items
            WHERE production_order_id = target_id;

            DELETE FROM production_orders
            WHERE id = target_id;
        END $$;
        """
    )


def downgrade():
    # Deleted workflow data cannot be reconstructed safely.
    pass

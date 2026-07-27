"""normalize payroll QR scan identities

Revision ID: 0054_payroll_qr_ids
Revises: 0053_payroll_qr_control
Create Date: 2026-07-15
"""

from alembic import op


revision = "0054_payroll_qr_ids"
down_revision = "0053_payroll_qr_control"
branch_labels = None
depends_on = None


def upgrade():
    # Early scanner builds prefixed issued label IDs with ``payroll:``. Merge
    # those duplicate rows back into the original issued label so the control
    # panel shows one label whose status changes from available to scanned.
    op.execute(
        """
        UPDATE payroll_qr_labels AS target
        SET status = 'scanned',
            payroll_record_id = record.id,
            last_scanned_at = record.scanned_at,
            returned_at = NULL,
            returned_by = NULL,
            updated_at = NOW()
        FROM payroll_records AS record
        WHERE record.scan_uid LIKE 'payroll:PY:%'
          AND record.raw_work_json ->> 'label_id' = target.label_uid
          AND NOT EXISTS (
              SELECT 1
              FROM payroll_records AS other
              WHERE other.id <> record.id
                AND other.scan_uid = target.label_uid
          )
        """
    )
    op.execute(
        """
        UPDATE payroll_records AS record
        SET original_scan_uid = record.raw_work_json ->> 'label_id',
            scan_uid = record.raw_work_json ->> 'label_id',
            updated_at = NOW()
        WHERE record.scan_uid LIKE 'payroll:PY:%'
          AND NULLIF(record.raw_work_json ->> 'label_id', '') IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM payroll_qr_labels AS target
              WHERE target.label_uid = record.raw_work_json ->> 'label_id'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM payroll_records AS other
              WHERE other.id <> record.id
                AND other.scan_uid = record.raw_work_json ->> 'label_id'
          )
        """
    )
    op.execute(
        """
        DELETE FROM payroll_qr_labels AS duplicate
        USING payroll_records AS record
        WHERE duplicate.payroll_record_id = record.id
          AND duplicate.label_uid LIKE 'payroll:PY:%'
          AND record.scan_uid <> duplicate.label_uid
          AND EXISTS (
              SELECT 1
              FROM payroll_qr_labels AS target
              WHERE target.label_uid = record.scan_uid
          )
        """
    )


def downgrade():
    # The migration repairs duplicate identities and is intentionally not
    # reversible; restoring the invalid duplicate rows would corrupt status.
    pass

"""remove BT prefix from production batch numbers

Revision ID: 0058_numeric_batch_numbers
Revises: 0057_payroll_qr_cutting_passport
Create Date: 2026-07-16
"""

from alembic import op


revision = "0058_numeric_batch_numbers"
down_revision = "0057_payroll_qr_cutting_passport"
branch_labels = None
depends_on = None


def upgrade():
    for table, column in (
        ("production_batches", "batch_no"),
        ("payroll_records", "batch_no"),
        ("payroll_qr_labels", "batch_no"),
        ("cutting_passports", "lot_no"),
    ):
        op.execute(
            f"UPDATE {table} "
            f"SET {column} = SUBSTRING({column} FROM 4) "
            f"WHERE UPPER({column}) LIKE 'BT-%'"
        )


def downgrade():
    for table, column in (
        ("production_batches", "batch_no"),
        ("payroll_records", "batch_no"),
        ("payroll_qr_labels", "batch_no"),
        ("cutting_passports", "lot_no"),
    ):
        op.execute(
            f"UPDATE {table} "
            f"SET {column} = 'BT-' || {column} "
            f"WHERE {column} IS NOT NULL AND {column} <> '' AND UPPER({column}) NOT LIKE 'BT-%'"
        )

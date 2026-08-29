"""Separate package and receipt data by packaging department.

Revision ID: 0089_packaging_departments
Revises: 0088_eco_cotton_sewing_bands
"""

from alembic import op
import sqlalchemy as sa


revision = "0089_packaging_departments"
down_revision = "0088_eco_cotton_sewing_bands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("packages", sa.Column("packaging_department_code", sa.String(length=16), nullable=True))
    op.add_column("packaging_receipts", sa.Column("packaging_department_code", sa.String(length=16), nullable=True))

    op.execute(
        """
        UPDATE packages AS package
        SET packaging_department_code = COALESCE(
            (
                SELECT CASE WHEN department.code IN ('PKG', 'BPK', 'ECP') THEN department.code ELSE 'PKG' END
                FROM work_orders AS work_order
                JOIN departments AS department ON department.id = work_order.department_id
                WHERE work_order.production_order_id = package.production_order_id
                  AND work_order.operation = 'packaging'
                ORDER BY
                    CASE
                        WHEN package.production_batch_id IS NOT NULL
                         AND work_order.production_batch_id = package.production_batch_id THEN 0
                        WHEN work_order.production_batch_id IS NULL THEN 1
                        ELSE 2
                    END,
                    work_order.id DESC
                LIMIT 1
            ),
            'PKG'
        )
        """
    )
    op.execute(
        """
        UPDATE packaging_receipts AS receipt
        SET packaging_department_code = COALESCE(
            (
                SELECT CASE WHEN department.code IN ('PKG', 'BPK', 'ECP') THEN department.code ELSE 'PKG' END
                FROM work_orders AS work_order
                JOIN departments AS department ON department.id = work_order.department_id
                WHERE work_order.id = receipt.work_order_id
                LIMIT 1
            ),
            'PKG'
        )
        """
    )

    op.alter_column("packages", "packaging_department_code", nullable=False, server_default="PKG")
    op.alter_column("packaging_receipts", "packaging_department_code", nullable=False, server_default="PKG")
    op.create_index("ix_packages_packaging_department_code", "packages", ["packaging_department_code"])
    op.create_index(
        "ix_packaging_receipts_packaging_department_code",
        "packaging_receipts",
        ["packaging_department_code"],
    )
    op.create_check_constraint(
        "ck_packages_packaging_department",
        "packages",
        "packaging_department_code IN ('PKG', 'BPK', 'ECP')",
    )
    op.create_check_constraint(
        "ck_packaging_receipts_department",
        "packaging_receipts",
        "packaging_department_code IN ('PKG', 'BPK', 'ECP')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_packaging_receipts_department", "packaging_receipts", type_="check")
    op.drop_constraint("ck_packages_packaging_department", "packages", type_="check")
    op.drop_index("ix_packaging_receipts_packaging_department_code", table_name="packaging_receipts")
    op.drop_index("ix_packages_packaging_department_code", table_name="packages")
    op.drop_column("packaging_receipts", "packaging_department_code")
    op.drop_column("packages", "packaging_department_code")

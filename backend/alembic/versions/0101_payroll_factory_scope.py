"""isolate payroll data by operating factory

Revision ID: 0101_payroll_factory_scope
Revises: 0100_material_roll_weights
"""

from alembic import op
import sqlalchemy as sa


revision = "0101_payroll_factory_scope"
down_revision = "0100_material_roll_weights"
branch_labels = None
depends_on = None


FACTORY_CHECK = "factory_code IN ('MIL', 'BST', 'ECO')"


def _add_factory_column(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column("factory_code", sa.String(length=3), nullable=True, server_default="MIL"),
    )


def upgrade() -> None:
    for table_name in (
        "employees",
        "payroll_periods",
        "payroll_records",
        "payroll_qr_labels",
        "payroll_adjustments",
    ):
        _add_factory_column(table_name)

    op.execute(
        """
        UPDATE employees AS e
        SET factory_code = COALESCE(
            (SELECT u.factory_code FROM users AS u WHERE u.id = e.user_id),
            (SELECT CASE
                WHEN d.code IN ('BST', 'BPK') THEN 'BST'
                WHEN d.code IN ('ECT', 'ECO', 'ECP') THEN 'ECO'
                ELSE 'MIL' END
             FROM departments AS d WHERE d.id = e.department_id),
            'MIL'
        )
        """
    )
    op.execute(
        """
        UPDATE payroll_records AS r
        SET factory_code = COALESCE(
            (SELECT e.factory_code FROM employees AS e WHERE e.id = r.employee_id),
            (SELECT u.factory_code FROM users AS u WHERE u.id = r.scanned_by),
            'MIL'
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT r.payroll_period_id
                FROM payroll_records AS r
                WHERE r.payroll_period_id IS NOT NULL
                GROUP BY r.payroll_period_id
                HAVING COUNT(DISTINCT r.factory_code) > 1
            ) THEN
                RAISE EXCEPTION 'Existing payroll period contains records from multiple factories';
            END IF;
        END $$
        """
    )
    op.execute(
        """
        UPDATE payroll_periods AS p
        SET factory_code = COALESCE(
            (SELECT MIN(r.factory_code) FROM payroll_records AS r WHERE r.payroll_period_id = p.id),
            (SELECT u.factory_code FROM users AS u WHERE u.id = p.created_by),
            'MIL'
        )
        """
    )
    op.execute(
        """
        UPDATE payroll_qr_labels AS q
        SET factory_code = COALESCE(
            (SELECT r.factory_code FROM payroll_records AS r WHERE r.id = q.payroll_record_id),
            (SELECT f.factory_code FROM sewing_flows AS f WHERE f.id = q.sewing_flow_id),
            (SELECT CASE WHEN COUNT(DISTINCT b.sewing_factory_code) = 1
                         THEN MIN(b.sewing_factory_code) ELSE NULL END
             FROM bundles AS b
             WHERE b.production_order_id = q.production_order_id
               AND b.status <> 'cancelled'
               AND b.sewing_factory_code IS NOT NULL),
            (SELECT u.factory_code FROM users AS u WHERE u.id = q.issued_by),
            'MIL'
        )
        """
    )
    op.execute(
        """
        UPDATE payroll_adjustments AS a
        SET factory_code = COALESCE(
            (SELECT e.factory_code FROM employees AS e WHERE e.id = a.employee_id),
            (SELECT u.factory_code FROM users AS u WHERE u.id = a.created_by),
            'MIL'
        )
        """
    )

    for table_name in (
        "employees",
        "payroll_periods",
        "payroll_records",
        "payroll_qr_labels",
        "payroll_adjustments",
    ):
        op.alter_column(table_name, "factory_code", nullable=False, server_default="MIL")
        op.create_check_constraint(f"ck_{table_name}_factory_code", table_name, FACTORY_CHECK)
        op.create_index(f"ix_{table_name}_factory_code", table_name, ["factory_code"])

    op.drop_index("ix_employees_employee_no", table_name="employees")
    op.create_index("ix_employees_employee_no", "employees", ["employee_no"])
    op.create_unique_constraint(
        "uq_employees_factory_employee_no",
        "employees",
        ["factory_code", "employee_no"],
    )

    period_constraints = {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_unique_constraints("payroll_periods")
    }
    op.drop_index("ix_payroll_periods_period_no", table_name="payroll_periods")
    if "uq_payroll_periods_period_no" in period_constraints:
        op.drop_constraint("uq_payroll_periods_period_no", "payroll_periods", type_="unique")
    op.create_index("ix_payroll_periods_period_no", "payroll_periods", ["period_no"])
    op.create_unique_constraint(
        "uq_payroll_periods_factory_period_no",
        "payroll_periods",
        ["factory_code", "period_no"],
    )

    op.drop_constraint("uq_payroll_records_scan_uid", "payroll_records", type_="unique")
    op.drop_constraint("uq_payroll_records_dedupe_key", "payroll_records", type_="unique")
    op.create_unique_constraint(
        "uq_payroll_records_factory_scan_uid",
        "payroll_records",
        ["factory_code", "scan_uid"],
    )
    op.create_unique_constraint(
        "uq_payroll_records_factory_dedupe_key",
        "payroll_records",
        ["factory_code", "dedupe_key"],
    )

    op.drop_constraint("uq_payroll_qr_labels_label_uid", "payroll_qr_labels", type_="unique")
    op.create_unique_constraint(
        "uq_payroll_qr_labels_factory_label_uid",
        "payroll_qr_labels",
        ["factory_code", "label_uid"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_payroll_qr_labels_factory_label_uid", "payroll_qr_labels", type_="unique")
    op.create_unique_constraint("uq_payroll_qr_labels_label_uid", "payroll_qr_labels", ["label_uid"])

    op.drop_constraint("uq_payroll_records_factory_dedupe_key", "payroll_records", type_="unique")
    op.drop_constraint("uq_payroll_records_factory_scan_uid", "payroll_records", type_="unique")
    op.create_unique_constraint("uq_payroll_records_dedupe_key", "payroll_records", ["dedupe_key"])
    op.create_unique_constraint("uq_payroll_records_scan_uid", "payroll_records", ["scan_uid"])

    op.drop_constraint("uq_payroll_periods_factory_period_no", "payroll_periods", type_="unique")
    op.drop_index("ix_payroll_periods_period_no", table_name="payroll_periods")
    op.create_index("ix_payroll_periods_period_no", "payroll_periods", ["period_no"], unique=True)

    op.drop_constraint("uq_employees_factory_employee_no", "employees", type_="unique")
    op.drop_index("ix_employees_employee_no", table_name="employees")
    op.create_index("ix_employees_employee_no", "employees", ["employee_no"], unique=True)

    for table_name in reversed((
        "employees",
        "payroll_periods",
        "payroll_records",
        "payroll_qr_labels",
        "payroll_adjustments",
    )):
        op.drop_index(f"ix_{table_name}_factory_code", table_name=table_name)
        op.drop_constraint(f"ck_{table_name}_factory_code", table_name, type_="check")
        op.drop_column(table_name, "factory_code")

"""Persistence for an already validated correction; caller owns the transaction."""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.schemas.payroll_split_correction import SplitAllocationPartUpdate
from app.models import Employee, PayrollQrLabel, PayrollRecord


def apply_split_part_correction(
    db: Session, *, label: PayrollQrLabel, record: PayrollRecord,
    employee: Employee, department_name: str | None, part: SplitAllocationPartUpdate, amount: Decimal,
) -> None:
    label.quantity = part.quantity
    label.operation_name = part.operation_name
    label.rate_per_piece = part.rate_per_piece
    label.payload = None
    record.employee_id = employee.id
    record.employee_user_id = employee.user_id
    record.quantity = part.quantity
    record.operation_name = part.operation_name
    record.rate_per_piece = part.rate_per_piece
    record.total_amount = amount
    record.raw_employee_json = {
        "type": "employee_payroll", "employee_id": employee.id,
        "employee_name": employee.full_name, "employee_user_id": employee.user_id,
        "employee_no": employee.employee_no,
        "department_id": employee.department_id,
        "department_name": department_name,
    }
    record.raw_work_json = {
        **(record.raw_work_json or {}), "operation_name": part.operation_name,
        "quantity": part.quantity, "rate_per_piece": str(part.rate_per_piece),
    }
    # Both rows already belong to the supplied Session. Identity, work date,
    # status, payroll period and original scan/dedupe keys remain untouched.

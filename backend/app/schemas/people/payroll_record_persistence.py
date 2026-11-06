"""Payroll record and scan-label writes; the supplied Session's caller owns commit."""
from typing import Any

from sqlalchemy.orm import Session

from app.schemas import PayrollQrLabel, PayrollRecord


def insert_payroll_record(
    db: Session, *, factory_code: str, actor_id: int,
    data: dict[str, Any], status: str,
) -> PayrollRecord:
    record = PayrollRecord(
        factory_code=factory_code,
        payroll_period_id=data["payroll_period_id"],
        scan_uid=data["scan_uid"],
        original_scan_uid=data["scan_uid"],
        dedupe_key=data["dedupe_key"],
        employee_id=data["employee_id"],
        employee_user_id=data["employee_user_id"],
        production_order_id=data["production_order_id"],
        sales_order_id=data["sales_order_id"],
        work_order_id=data["work_order_id"],
        production_batch_id=data["production_batch_id"],
        model_id=data["model_id"],
        production_no=data["production_no"],
        sales_order_no=data["sales_order_no"],
        batch_no=data["batch_no"],
        model_code=data["model_code"],
        operation_section=data["operation_section"],
        operation_code=data["operation_code"],
        operation_name=data["operation_name"],
        quantity=data["quantity"],
        rate_per_piece=data["rate_per_piece"],
        currency=data["currency"],
        total_amount=data["total_amount"],
        scanned_by=actor_id,
        scanned_at=data["scanned_at"],
        source=data["source"],
        raw_employee_json=data["raw_employee_json"],
        raw_work_json=data["raw_work_json"],
        status=status,
        notes=data["notes"],
    )
    db.add(record)
    db.flush()
    return record


def add_scanned_payroll_label(db: Session, *, record: PayrollRecord, label_uid: str) -> PayrollQrLabel:
    label = PayrollQrLabel(
        factory_code=record.factory_code,
        label_uid=label_uid,
        issued_at=record.scanned_at,
        issued_by=record.scanned_by,
    )
    db.add(label)
    return label


def apply_scanned_payroll_label(db: Session, label: PayrollQrLabel, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(label, key, value)
    db.flush()


def apply_payroll_record_changes(record: PayrollRecord, changes: dict[str, Any]) -> None:
    for key, value in changes.items():
        setattr(record, key, value)


def build_split_payroll_qr_label(**values) -> PayrollQrLabel:
    return PayrollQrLabel(**values)


def add_split_payroll_qr_row(db: Session, label: PayrollQrLabel) -> None:
    db.add(label)

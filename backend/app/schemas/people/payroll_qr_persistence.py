"""Payroll QR issuance writes use the caller's Session without hidden commits."""
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.people.payroll import PayrollQrLabel


def stage_issue_qr_label(db: Session, *, factory_code: str, label_uid: str) -> PayrollQrLabel:
    label = PayrollQrLabel(factory_code=factory_code, label_uid=label_uid)
    db.add(label)
    return label


def apply_payroll_qr_changes(label: PayrollQrLabel, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(label, key, value)

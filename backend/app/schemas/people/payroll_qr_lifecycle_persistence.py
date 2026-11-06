"""Unscanned payroll QR split/delete writes share the operation's Session."""
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.people.payroll import PayrollQrLabel


def stage_split_qr_label(
    db: Session, *, factory_code: str, label_uid: str, copy_index: int,
    quantity: Decimal, copied_fields: dict[str, Any],
) -> PayrollQrLabel:
    child = PayrollQrLabel(
        factory_code=factory_code, label_uid=label_uid, copy_index=copy_index,
        quantity=quantity, **copied_fields,
    )
    db.add(child)
    return child


def stage_delete_qr_labels(db: Session, labels: list[PayrollQrLabel]) -> None:
    for label in labels:
        db.delete(label)

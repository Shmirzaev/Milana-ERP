"""HR workspace writes in the operation's supplied transaction."""

from sqlalchemy.orm import Session

from app.schemas import HrOrgUnit


def insert_org_unit(db: Session, *, factory_code: str, values: dict) -> HrOrgUnit:
    row = HrOrgUnit(factory_code=factory_code, **values)
    db.add(row)
    return row


def delete_org_unit_row(db: Session, row: HrOrgUnit) -> None:
    db.delete(row)

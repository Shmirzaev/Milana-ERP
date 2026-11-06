"""HR workspace writes in the operation's supplied transaction."""

from sqlalchemy.orm import Session

from app.schemas import HrOrgUnit, HrPosition, HrRecruitmentCandidate


def insert_org_unit(db: Session, *, factory_code: str, values: dict) -> HrOrgUnit:
    row = HrOrgUnit(factory_code=factory_code, **values)
    db.add(row)
    return row


def delete_org_unit_row(db: Session, row: HrOrgUnit) -> None:
    db.delete(row)


def insert_position(db: Session, *, factory_code: str, values: dict) -> HrPosition:
    row = HrPosition(factory_code=factory_code, **values)
    db.add(row)
    return row


def update_position_row(db: Session, *, row: HrPosition, values: dict) -> None:
    for key, value in values.items():
        setattr(row, key, value)


def insert_candidate(db: Session, *, factory_code: str, values: dict) -> HrRecruitmentCandidate:
    row = HrRecruitmentCandidate(factory_code=factory_code, **values)
    db.add(row)
    return row


def update_candidate_row(db: Session, *, row: HrRecruitmentCandidate, values: dict) -> None:
    for key, value in values.items():
        setattr(row, key, value)

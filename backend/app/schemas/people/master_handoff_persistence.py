"""Narrow roster mutations; caller owns validation, locks and transaction."""
from copy import deepcopy
from sqlalchemy.orm import Session, object_session

from app.schemas import Employee


def assign_current_master(db: Session, employee: Employee, *, manager_id: int | None,
                          position: str | None, profile: dict) -> None:
    if object_session(employee) is not db:
        raise ValueError("Employee must belong to the supplied Session")
    employee.manager_employee_id = manager_id
    employee.position = position
    merged = deepcopy(employee.hr_profile_json or {})
    for key in ("section", "workplace"):
        if key in profile:
            merged[key] = deepcopy(profile[key])
    employee.hr_profile_json = merged

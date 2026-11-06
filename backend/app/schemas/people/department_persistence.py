"""Department writes in the caller's transaction."""

from sqlalchemy.orm import Session

from app.schemas import Department


def insert_department(db: Session, *, name: str, code: str) -> Department:
    department = Department(name=name, code=code)
    db.add(department)
    return department

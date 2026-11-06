"""Role writes in the business operation's supplied transaction."""
from sqlalchemy.orm import Session

from app.schemas import Role


def add_role(db: Session, *, name: str, permissions: list[str]) -> Role:
    role = Role(name=name, permissions=permissions)
    db.add(role)
    db.flush()
    return role

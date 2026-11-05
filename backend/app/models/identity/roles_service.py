"""Role operations; callers supply the authenticated HTTP context and Session."""
from sqlalchemy.orm import Session

from app.schemas import Role


def list_roles(db: Session) -> list[Role]:
    """Read every role for an authenticated account; no transaction is committed."""
    return db.query(Role).all()

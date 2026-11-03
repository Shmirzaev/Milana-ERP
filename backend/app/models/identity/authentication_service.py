"""Authentication decisions and factory-switch auditing; token transport stays in routes."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.audit_service import log_action
from app.models.factory_scope_service import authorize_login_factory, selected_factory_code
from app.schemas import User


def select_session_factory(db: Session, user: User, requested_factory_code: str) -> str:
    if not 1 <= len(requested_factory_code) <= 3:
        raise HTTPException(422, "Factory code must be 1 to 3 characters")
    factory_code = authorize_login_factory(user, requested_factory_code)
    previous = selected_factory_code(user)
    if factory_code != previous:
        log_action(
            db, user, "switch_factory", "User", user.id,
            old_value={"factory_code": previous}, new_value={"factory_code": factory_code},
        )
        db.commit()
    return factory_code

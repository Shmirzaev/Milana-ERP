"""Read-only authentication decisions; token and cookie transport stay in routes."""

from fastapi import HTTPException

from app.models.factory_scope_service import authorize_login_factory
from app.schemas import User


def select_session_factory(user: User, requested_factory_code: str) -> str:
    if not 1 <= len(requested_factory_code) <= 3:
        raise HTTPException(422, "Factory code must be 1 to 3 characters")
    return authorize_login_factory(user, requested_factory_code)

from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if not token:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or unknown user")
    # Reject tokens issued before the user's credentials were last rotated, so a
    # password change/reset invalidates any previously stolen session.
    valid_from = getattr(user, "tokens_valid_from", None)
    issued_at = payload.get("iat")
    if valid_from is not None and issued_at is not None:
        from app.core.dt import as_utc
        if int(issued_at) < int(as_utc(valid_from).timestamp()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired, please sign in again")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]


def normalize_permissions(values) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        if not isinstance(value, str):
            continue
        permission = value.strip()
        if not permission or permission in seen:
            continue
        seen.add(permission)
        out.append(permission)
    return out


def user_permissions(user: User) -> list[str]:
    permissions: list[str] = []
    if user.role and user.role.permissions:
        permissions.extend(user.role.permissions)
    permissions.extend(getattr(user, "extra_permissions", None) or [])
    return normalize_permissions(permissions)


def is_admin(user: User) -> bool:
    return "*" in user_permissions(user) or (user.role and user.role.name.lower() == "admin")


def require_permissions(*perms: str):
    """Dependency factory: ensures the current user has at least one of the given permissions, or has '*'."""

    def _checker(user: CurrentUser) -> User:
        granted = user_permissions(user)
        if "*" in granted:
            return user
        if not perms:
            return user
        if any(p in granted for p in perms):
            return user
        raise HTTPException(status_code=403, detail=f"Missing permission. Need any of: {list(perms)}")

    return _checker

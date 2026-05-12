from fastapi import APIRouter, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
from fastapi import Depends

from app.core.deps import DbSession, CurrentUser, user_permissions
from app.core.security import verify_password, create_access_token
from app.models import User
from app.schemas.auth import LoginIn, TokenOut, UserMe

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login_oauth(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession):
    """OAuth2-compatible login (form: username=email, password)."""
    email = form_data.username.lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(401, "User inactive")
    token = create_access_token(user.id)
    return TokenOut(access_token=token)


@router.post("/login-json", response_model=TokenOut)
def login_json(payload: LoginIn, db: DbSession):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(401, "User inactive")
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserMe)
def me(user: CurrentUser):
    return UserMe(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role.name if user.role else None,
        department=user.department.name if user.department else None,
        permissions=user_permissions(user),
    )

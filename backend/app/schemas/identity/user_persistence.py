"""Account and setup-token writes in the caller's transaction."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.schemas import PasswordResetToken, User


def record_user_login_activity(db: Session, user: User, now: datetime) -> None:
    user.last_login_at = now
    user.last_seen_at = now


def record_user_seen(db: Session, user: User, now: datetime) -> None:
    user.last_seen_at = now


def set_user_profile(db: Session, user: User, *, name: str) -> None:
    user.name = name


def set_password_and_invalidate_reset_tokens(db: Session, user: User, password_hash: str, now: datetime) -> None:
    user.password_hash = password_hash
    user.tokens_valid_from = now
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session="fetch")


def add_user(
    db: Session, *, name: str, email: str, password_hash: str,
    role_id: int | None, department_id: int | None, factory_code: str,
    extra_permissions: list[str], access_policy: dict | None, is_active: bool,
) -> User:
    user = User(
        name=name, email=email, password_hash=password_hash, role_id=role_id,
        department_id=department_id, factory_code=factory_code,
        extra_permissions=extra_permissions, access_policy=access_policy,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return user


def add_password_reset_token(
    db: Session, *, user_id: int, token_hash: str, expires_at: datetime,
) -> PasswordResetToken:
    token = PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(token)
    return token

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.schemas import User
from app.schemas.identity.user_persistence import set_password_and_invalidate_reset_tokens


def lock_user_for_credential_change(
    db: Session,
    user_id: int,
    *,
    require_active: bool,
) -> User | None:
    query = db.query(User).filter(User.id == user_id)
    if require_active:
        query = query.filter(User.is_active.is_(True))
    return query.populate_existing().with_for_update(of=User).first()


def apply_password_credential_change(
    db: Session,
    user: User,
    new_password: str,
    *,
    changed_at: datetime | None = None,
) -> datetime:
    """Rotate one password and every credential derived from the old state.

    Callers must hold the target User row lock.  Reset links are invalidated in
    the same transaction so self-service, token-reset and administrator changes
    cannot revive one another's stale credential state.
    """
    now = changed_at or datetime.now(timezone.utc)
    set_password_and_invalidate_reset_tokens(db, user, hash_password(new_password), now)
    return now

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.config import settings
from app.core.security import validate_password_strength
from app.models import PasswordResetToken, User


def validate_credential_runtime_configuration(*, strict_security_required: bool) -> None:
    for setting_name in ("INITIAL_ADMIN_PASSWORD", "AI_MONITOR_PASSWORD"):
        password = str(getattr(settings, setting_name, "") or "")
        if not password:
            continue
        try:
            validate_password_strength(password)
        except ValueError as exc:
            raise RuntimeError(f"{setting_name} does not satisfy the configured password policy") from exc
    if strict_security_required and settings.SEED_DEMO_USERS:
        raise RuntimeError("SEED_DEMO_USERS must be false in production/public deployments")


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
    user.password_hash = hash_password(new_password)
    user.tokens_valid_from = now
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session="fetch")
    return now

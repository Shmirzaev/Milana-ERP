from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import user_permissions
from app.db.session import SessionLocal
from app.models import Notification, PasswordResetToken, User
from app.services.email import send_password_reset_email, send_password_setup_email

log = logging.getLogger(__name__)

EMAIL_NOT_CONFIGURED_MESSAGE = (
    "Email delivery is not configured. Set RESEND_API_KEY and RESEND_FROM_EMAIL, "
    "or set SMTP_HOST and SMTP_FROM_EMAIL."
)


@dataclass(frozen=True)
class PasswordEmailDelivery:
    sent: bool
    error: str | None = None


def password_reset_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_reset_url(token: str) -> str:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    return f"{base}/reset-password?token={token}"


def create_password_reset_token(db: Session, user: User) -> str:
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_MINUTES)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=password_reset_hash(raw_token),
            expires_at=expires_at,
        )
    )
    return raw_token


def _safe_reset_delivery_error(error: object) -> str:
    safe_message = getattr(error, "safe_message", None)
    if isinstance(safe_message, str) and safe_message.strip():
        return safe_message
    # Delivery/provider errors can echo the submitted email body, including the
    # reset URL. Never persist or log raw provider text for reset emails.
    return "Email delivery failed; provider details suppressed because they may contain reset-token material."


def notify_admins_about_password_email_failure(
    user_id: int,
    reset_url: str,
    error: str,
    *,
    email_kind: str = "reset",
) -> None:
    _ = reset_url  # Never persist raw reset tokens in notifications or audit trails.
    safe_error = _safe_reset_delivery_error(error)
    db = SessionLocal()
    title = "Password setup email failed" if email_kind == "setup" else "Password reset email failed"
    action = "was created" if email_kind == "setup" else "requested a password reset"
    followup = (
        "Do not share stored links; send a fresh setup/reset link after email delivery is restored."
        if email_kind == "setup"
        else "Do not share stored links; generate a fresh reset after email delivery is restored."
    )
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return
        recipients = [
            admin
            for admin in db.query(User).filter(User.is_active.is_(True)).all()
            if "*" in user_permissions(admin) or "admin.users" in user_permissions(admin)
        ]
        for admin in recipients:
            db.add(
                Notification(
                    user_id=admin.id,
                    title=title,
                    message=(
                        f"{user.name} ({user.email}) {action}, but email delivery failed. "
                        f"{followup} Error: {safe_error}"
                    ),
                    link="/admin/users",
                )
            )
        if recipients:
            db.commit()
    except Exception:
        db.rollback()
        log.exception("Could not create password email failure notification for user_id=%s", user_id)
    finally:
        db.close()


def send_password_email_safely(
    email: str,
    name: str,
    reset_url: str,
    user_id: int,
    email_kind: str = "reset",
) -> None:
    send_password_email(email, name, reset_url, user_id, email_kind)


def send_password_email(
    email: str,
    name: str,
    reset_url: str,
    user_id: int,
    email_kind: str = "reset",
) -> PasswordEmailDelivery:
    try:
        sender = send_password_setup_email if email_kind == "setup" else send_password_reset_email
        if sender(email, name, reset_url):
            log.info("Password %s email sent to %s", email_kind, email)
            return PasswordEmailDelivery(sent=True)
        else:
            log.warning("Password %s email not sent to %s: email delivery is not configured", email_kind, email)
            notify_admins_about_password_email_failure(
                user_id,
                reset_url,
                EMAIL_NOT_CONFIGURED_MESSAGE,
                email_kind=email_kind,
            )
            return PasswordEmailDelivery(sent=False, error=EMAIL_NOT_CONFIGURED_MESSAGE)
    except Exception as exc:
        safe_error = _safe_reset_delivery_error(exc)
        log.warning(
            "Password %s email failed for %s (%s); details suppressed because they may contain reset-token material",
            email_kind,
            email,
            type(exc).__name__,
        )
        notify_admins_about_password_email_failure(user_id, reset_url, exc, email_kind=email_kind)
        return PasswordEmailDelivery(sent=False, error=safe_error)

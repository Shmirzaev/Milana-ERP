from calendar import timegm
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext

from app.core.config import settings

# bcrypt_sha256 pre-hashes the password with SHA-256, sidestepping bcrypt's
# silent 72-byte truncation. Plain "bcrypt" is kept so existing stored hashes
# still verify; it's marked deprecated and will rehash on next successful login.
pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")

LEGACY_DEFAULT_ADMIN_EMAIL = "admin@example.com"
LEGACY_DEFAULT_ADMIN_PASSWORD = "admin" + "12345"
BLOCKED_SHARED_PASSWORDS = {
    LEGACY_DEFAULT_ADMIN_PASSWORD,
    "demo12345",
    "password",
    "password123",
    "admin",
    "admin123",
    "qwerty123",
}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def password_strength_errors(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if password != password.strip():
        errors.append("not start or end with spaces")
    if password.lower() in BLOCKED_SHARED_PASSWORDS:
        errors.append("not use a shared default password")
    if not any(ch.isalpha() for ch in password):
        errors.append("include a letter")
    if not any(ch.isdigit() for ch in password):
        errors.append("include a number")
    return errors


def validate_password_strength(password: str) -> None:
    errors = password_strength_errors(password)
    if errors:
        raise ValueError("Password must " + ", ".join(errors) + ".")


def is_legacy_default_admin_login(email: str, password: str) -> bool:
    return (
        normalize_email(email) == LEGACY_DEFAULT_ADMIN_EMAIL
        and password == LEGACY_DEFAULT_ADMIN_PASSWORD
    )


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": now.timestamp(),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRES_MINUTES)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
                             options={"verify_iat": False, "verify_exp": False})
        # Preserve jose's iat coercion and whole-second exp < now boundary.
        if "iat" in payload:
            int(payload["iat"])
        if "exp" in payload and int(payload["exp"]) < timegm(datetime.now(timezone.utc).utctimetuple()):
            raise ValueError("Signature has expired.")
        # The legacy decoder was given neither an audience nor an access token.
        if "aud" in payload:
            raise ValueError("Invalid audience")
        if "at_hash" in payload:
            raise ValueError("No access_token provided to compare against at_hash claim.")
        return payload
    except (InvalidTokenError, ValueError) as e:
        raise ValueError(f"Invalid token: {e}") from e

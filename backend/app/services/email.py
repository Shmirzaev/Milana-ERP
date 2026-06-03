from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings


def email_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def send_email(to_email: str, subject: str, text_body: str) -> bool:
    if not email_configured():
        return False

    message = EmailMessage()
    message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body)

    if settings.SMTP_USE_SSL:
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        ) as smtp:
            _login_if_needed(smtp)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls(context=ssl.create_default_context())
            _login_if_needed(smtp)
            smtp.send_message(message)

    return True


def send_password_reset_email(to_email: str, display_name: str, reset_url: str) -> bool:
    greeting = display_name.strip() or "there"
    body = (
        f"Hi {greeting},\n\n"
        "We received a request to reset your Milana ERP password.\n\n"
        f"Reset your password here:\n{reset_url}\n\n"
        f"This link expires in {settings.PASSWORD_RESET_TOKEN_MINUTES} minutes. "
        "If you did not request this, you can ignore this email.\n"
    )
    return send_email(to_email, "Reset your Milana ERP password", body)


def _login_if_needed(smtp: smtplib.SMTP) -> None:
    if settings.SMTP_USERNAME:
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)

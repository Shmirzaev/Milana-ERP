from __future__ import annotations

import smtplib
import ssl
import json
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from app.core.config import settings


def email_configured() -> bool:
    return resend_configured() or smtp_configured()


def resend_configured() -> bool:
    return bool(settings.RESEND_API_KEY and (settings.RESEND_FROM_EMAIL or settings.SMTP_FROM_EMAIL))


def smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def send_email(to_email: str, subject: str, text_body: str) -> bool:
    if resend_configured():
        return _send_resend_email(to_email, subject, text_body)
    if smtp_configured():
        return _send_smtp_email(to_email, subject, text_body)
    return False


def _send_resend_email(to_email: str, subject: str, text_body: str) -> bool:
    from_email = settings.RESEND_FROM_EMAIL or settings.SMTP_FROM_EMAIL
    from_value = formataddr((settings.SMTP_FROM_NAME, from_email))
    payload = json.dumps({
        "from": from_value,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
    }).encode("utf-8")
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            content=payload,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "milana-erp/1.0",
            },
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        # Response bodies from email providers can echo submitted message content
        # (including password-reset URLs). Do not propagate provider text into
        # logs, notifications, or error handlers.
        raise RuntimeError(f"Resend API error {exc.response.status_code}") from exc


def _send_smtp_email(to_email: str, subject: str, text_body: str) -> bool:
    if not smtp_configured():
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


def send_password_setup_email(to_email: str, display_name: str, setup_url: str) -> bool:
    greeting = display_name.strip() or "there"
    body = (
        f"Hi {greeting},\n\n"
        "A Milana ERP account has been created for you.\n\n"
        f"Set your password here:\n{setup_url}\n\n"
        f"This link expires in {settings.PASSWORD_RESET_TOKEN_MINUTES} minutes. "
        "If you were not expecting this account, contact your administrator.\n"
    )
    return send_email(to_email, "Set up your Milana ERP password", body)


def _login_if_needed(smtp: smtplib.SMTP) -> None:
    if settings.SMTP_USERNAME:
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)

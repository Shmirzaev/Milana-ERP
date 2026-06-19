from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from app.core.config import settings


class EmailDeliveryError(RuntimeError):
    def __init__(self, message: str, safe_message: str):
        super().__init__(message)
        self.safe_message = safe_message


def email_configured() -> bool:
    return resend_configured() or smtp_configured()


def resend_configured() -> bool:
    return bool(settings.RESEND_API_KEY and settings.RESEND_FROM_EMAIL)


def smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def send_email(to_email: str, subject: str, text_body: str) -> bool:
    if resend_configured():
        try:
            return _send_resend_email(to_email, subject, text_body)
        except EmailDeliveryError:
            if not smtp_configured():
                raise
    if smtp_configured():
        return _send_smtp_email(to_email, subject, text_body)
    return False


def _send_resend_email(to_email: str, subject: str, text_body: str) -> bool:
    from_value = formataddr((settings.SMTP_FROM_NAME, settings.RESEND_FROM_EMAIL))
    payload = {
        "from": from_value,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
    }
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
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
        status_code = exc.response.status_code
        raise EmailDeliveryError(
            f"Resend API error {status_code}",
            _resend_safe_error(status_code),
        ) from exc
    except httpx.RequestError as exc:
        raise EmailDeliveryError(
            "Resend API request failed",
            "Email delivery failed: could not reach the Resend API. Check network access or use SMTP settings.",
        ) from exc


def _resend_safe_error(status_code: int) -> str:
    if status_code in {401, 403}:
        return "Email delivery failed: Resend rejected the API key or sender. Check RESEND_API_KEY and RESEND_FROM_EMAIL."
    if status_code == 422:
        return "Email delivery failed: Resend rejected the sender or recipient. Check that RESEND_FROM_EMAIL is verified."
    if status_code == 429:
        return "Email delivery failed: Resend rate limit was reached. Try again later or use SMTP settings."
    return f"Email delivery failed: Resend API returned HTTP {status_code}. Check RESEND_API_KEY and RESEND_FROM_EMAIL."


def _send_smtp_email(to_email: str, subject: str, text_body: str) -> bool:
    if not smtp_configured():
        return False

    message = EmailMessage()
    message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body)

    try:
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
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailDeliveryError(
            "SMTP authentication failed",
            "Email delivery failed: SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD/app password.",
        ) from exc
    except smtplib.SMTPSenderRefused as exc:
        raise EmailDeliveryError(
            "SMTP sender refused",
            "Email delivery failed: SMTP rejected SMTP_FROM_EMAIL. Check the sender email and mailbox permissions.",
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise EmailDeliveryError(
            "SMTP recipient refused",
            "Email delivery failed: SMTP rejected the recipient email address.",
        ) from exc
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, OSError) as exc:
        raise EmailDeliveryError(
            "SMTP connection failed",
            "Email delivery failed: could not connect to SMTP. Check SMTP_HOST, SMTP_PORT, SMTP_USE_TLS, and SMTP_USE_SSL.",
        ) from exc
    except smtplib.SMTPException as exc:
        raise EmailDeliveryError(
            "SMTP delivery failed",
            "Email delivery failed: SMTP provider rejected the message. Check SMTP settings and sender permissions.",
        ) from exc

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

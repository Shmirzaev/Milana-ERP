from app.core.config import settings
from app.services.email import EmailDeliveryError, resend_configured, send_email


def test_resend_requires_resend_from_email(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "test-resend-key")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "smtp@example.com")

    assert resend_configured() is False


def test_send_email_falls_back_to_smtp_when_resend_fails(monkeypatch):
    sent = {}

    def fail_resend(*args, **kwargs):
        raise EmailDeliveryError(
            "Resend failed",
            "Email delivery failed: Resend rejected the API key or sender.",
        )

    def send_smtp(to_email, subject, text_body):
        sent["to_email"] = to_email
        sent["subject"] = subject
        sent["text_body"] = text_body
        return True

    monkeypatch.setattr(settings, "RESEND_API_KEY", "test-resend-key")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "resend@example.com")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "smtp@example.com")
    monkeypatch.setattr("app.services.email._send_resend_email", fail_resend)
    monkeypatch.setattr("app.services.email._send_smtp_email", send_smtp)

    assert send_email("user@example.com", "Subject", "Body") is True
    assert sent == {
        "to_email": "user@example.com",
        "subject": "Subject",
        "text_body": "Body",
    }

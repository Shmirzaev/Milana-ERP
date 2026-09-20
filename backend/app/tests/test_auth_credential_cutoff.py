from datetime import datetime, timedelta, timezone

from jose import jwt
import pytest

from app.core import security
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import User


@pytest.fixture
def cutoff_user(client):
    with SessionLocal() as db:
        user = User(name="Cutoff test", email="cutoff@example.com", password_hash="test-only",
                    is_active=True, factory_code="BST", extra_permissions=[])
        db.add(user)
        db.commit()
        return user.id


@pytest.mark.parametrize("transport", ["bearer", "cookie"])
def test_same_second_rotation_rejects_earlier_token_but_accepts_later(client, cutoff_user, monkeypatch, transport):
    second = (datetime.now(timezone.utc) - timedelta(seconds=2)).replace(microsecond=0)

    class Clock(datetime):
        current = second.replace(microsecond=100000)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(security, "datetime", Clock)
    earlier = security.create_access_token(cutoff_user, {"factory_code": "BST"})
    with SessionLocal() as db:
        db.get(User, cutoff_user).tokens_valid_from = second.replace(microsecond=500000)
        db.commit()
    Clock.current = second.replace(microsecond=750000)
    later = security.create_access_token(cutoff_user, {"factory_code": "BST"})

    for token, expected in [(earlier, 401), (later, 200)]:
        client.cookies.clear()
        headers = {"Authorization": f"Bearer {token}"} if transport == "bearer" else {}
        if transport == "cookie":
            client.cookies.set(settings.AUTH_COOKIE_NAME, token)
        response = client.get("/api/auth/me", headers=headers)
        assert response.status_code == expected, response.text
    assert security.decode_token(later)["iat"] == Clock.current.timestamp()


@pytest.mark.parametrize("issued_at", ["missing", None, "not-a-time", True, float("nan"), float("inf")])
def test_rotated_account_rejects_missing_or_invalid_issue_time(client, cutoff_user, issued_at):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.get(User, cutoff_user).tokens_valid_from = now - timedelta(seconds=1)
        db.commit()
    claims = {"sub": str(cutoff_user), "exp": int(now.timestamp()) + 600, "factory_code": "BST"}
    if issued_at != "missing":
        claims["iat"] = issued_at
    token = jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401, response.text


def test_profile_update_preserves_factory_context(client, cutoff_user):
    headers = {"Authorization": f"Bearer {security.create_access_token(cutoff_user, {'factory_code': 'BST'})}"}
    before = client.get("/api/session/me", headers=headers)
    assert before.status_code == 200, before.text
    updated = client.patch("/api/session/me", headers=headers,
                           json={"name": "Updated name", "email": "cutoff@example.com"})
    assert updated.status_code == 200, updated.text
    for field in ("factory_code", "assigned_factory_code", "available_factories", "permissions", "access_configured"):
        assert updated.json()[field] == before.json()[field], field
    assert updated.json()["factory_code"] == "BST"


def test_legacy_integer_token_older_than_cutoff_is_rejected(client, cutoff_user):
    second = (datetime.now(timezone.utc) - timedelta(seconds=2)).replace(microsecond=0)
    with SessionLocal() as db:
        db.get(User, cutoff_user).tokens_valid_from = second.replace(microsecond=500000)
        db.commit()
    token = security.create_access_token(cutoff_user, {"iat": int(second.timestamp()), "factory_code": "BST"})
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401, response.text

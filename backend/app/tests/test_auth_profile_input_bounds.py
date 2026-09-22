"""Bound authenticated profile inputs to their persisted identity columns."""

from uuid import uuid4

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.models import AuditLog, User


def _account() -> tuple[int, str, dict[str, str]]:
    marker = uuid4().hex[:12]
    with SessionLocal() as db:
        user = User(
            name=f"Profile bounds {marker}",
            email=f"profile-bounds-{marker}@example.com",
            password_hash=hash_password("ProfileBounds!2026"),
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(user)
        db.commit()
        return int(user.id), str(user.email), {
            "Authorization": f"Bearer {create_access_token(user.id, {'factory_code': 'MIL'})}",
        }


def test_profile_name_accepts_column_limit_and_rejects_overflow_without_writes(client):
    user_id, email, headers = _account()
    accepted_name = "n" * 128
    accepted = client.patch(
        "/api/auth/me",
        headers=headers,
        json={"name": accepted_name, "email": email},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["name"] == accepted_name

    with SessionLocal() as db:
        audit_count = db.query(AuditLog).filter_by(
            user_id=user_id,
            action="update_profile",
            entity_type="User",
            entity_id=user_id,
        ).count()

    rejected = client.patch(
        "/api/auth/me",
        headers=headers,
        json={"name": "x" * 129, "email": f"changed-{email}"},
    )

    assert rejected.status_code == 422, rejected.text
    unauthorized = client.patch(
        "/api/auth/me",
        json={"name": "x" * 129, "email": email},
    )
    assert unauthorized.status_code == 401
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.name == accepted_name
        assert user.email == email
        assert db.query(AuditLog).filter_by(
            user_id=user_id,
            action="update_profile",
            entity_type="User",
            entity_id=user_id,
        ).count() == audit_count


def test_authenticated_factory_switch_rejects_oversized_code_and_preserves_auth_precedence(client):
    _, _, headers = _account()
    accepted = client.post(
        "/api/auth/switch-factory",
        headers=headers,
        json={"factory_code": "MIL"},
    )
    assert accepted.status_code == 200, accepted.text

    rejected = client.post(
        "/api/auth/switch-factory",
        headers=headers,
        json={"factory_code": "MILX"},
    )
    assert rejected.status_code == 422, rejected.text

    client.cookies.clear()
    unauthorized = client.post(
        "/api/auth/switch-factory",
        json={"factory_code": "MILX"},
    )
    assert unauthorized.status_code == 401

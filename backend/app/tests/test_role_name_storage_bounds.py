from uuid import uuid4

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Role, User


def _counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.query(Role).count(), db.query(AuditLog).filter(AuditLog.entity_type == "Role").count()


def _restricted_headers() -> dict[str, str]:
    with SessionLocal() as db:
        role = Role(name=f"No grant {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="Restricted role creator",
            email=f"restricted-role-{uuid4().hex}@example.com",
            password_hash="unused-role-bound-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(user)
        db.commit()
        token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def test_role_name_varchar_boundary_is_accepted(client, auth_headers):
    response = client.post(
        "/api/roles",
        json={"name": f"Role {uuid4().hex[:6]} " + "R" * 52, "permissions": []},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert len(response.json()["name"]) == 64


def test_role_name_overflow_rejects_without_writes_and_preserves_auth_and_permission_precedence(
    client, auth_headers
):
    restricted_headers = _restricted_headers()
    before = _counts()
    payload = {"name": "R" * 65, "permissions": []}

    unauthenticated = client.post("/api/roles", json=payload)
    assert unauthenticated.status_code == 401

    restricted = client.post(
        "/api/roles",
        json={"name": "R" * 65, "permissions": ["admin.super"]},
        headers=restricted_headers,
    )
    assert restricted.status_code == 403

    overlong = client.post("/api/roles", json=payload, headers=auth_headers)
    assert overlong.status_code == 422, overlong.text
    assert _counts() == before

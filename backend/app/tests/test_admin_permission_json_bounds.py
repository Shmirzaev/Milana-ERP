from uuid import uuid4

from app.db.session import SessionLocal
from app.models import AuditLog, Role, User


def _snapshot() -> tuple[int, int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(Role).count(),
            db.query(User).count(),
            db.query(AuditLog).filter(AuditLog.entity_type.in_(("Role", "User"))).count(),
            db.query(User.extra_permissions).filter(User.email == "permission-bounds-target@example.invalid").scalar() is not None,
        )


def _target_user() -> int:
    with SessionLocal.begin() as db:
        role = Role(name=f"Permission bounds target {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="Permission bounds target",
            email="permission-bounds-target@example.invalid",
            password_hash="unused-test-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=["finance.view"],
            is_active=True,
        )
        db.add(user)
        db.flush()
        return int(user.id)


def test_role_permission_json_accepts_bounded_legacy_vectors_and_rejects_overflow_without_writes(
    client, auth_headers,
):
    accepted = [f"custom.permission.{index:03}" for index in range(150)]
    response = client.post(
        "/api/roles",
        headers=auth_headers,
        json={"name": f"Bounded role {uuid4().hex[:8]}", "permissions": accepted},
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["permissions"]) == 150

    before = _snapshot()
    unauthenticated = client.post(
        "/api/roles",
        json={"name": f"Unauth grant {uuid4().hex[:8]}", "permissions": ["x" * 129]},
    )
    too_many = client.post(
        "/api/roles",
        headers=auth_headers,
        json={"name": f"Too many grants {uuid4().hex[:8]}", "permissions": ["finance.view"] * 151},
    )
    overlong = client.post(
        "/api/roles",
        headers=auth_headers,
        json={"name": f"Long grant {uuid4().hex[:8]}", "permissions": ["x" * 129]},
    )

    assert unauthenticated.status_code == 401, unauthenticated.text
    assert too_many.status_code == 422, too_many.text
    assert overlong.status_code == 422, overlong.text
    assert _snapshot() == before


def test_user_extra_permission_json_rejects_create_and_update_overflow_without_writes(
    client, auth_headers,
):
    target_id = _target_user()
    before = _snapshot()
    too_many = client.post(
        "/api/users",
        headers=auth_headers,
        json={
            "name": "Too many permission target",
            "email": f"permission-overflow-{uuid4().hex}@example.invalid",
            "password": "PermissionBounds!2026",
            "extra_permissions": ["finance.view"] * 151,
        },
    )
    overlong = client.patch(
        f"/api/users/{target_id}",
        headers=auth_headers,
        json={"name": "Must not be applied", "extra_permissions": ["x" * 129]},
    )
    overlong_policy = client.post(
        "/api/users",
        headers=auth_headers,
        json={
            "name": "Long scoped permission target",
            "email": f"permission-policy-overflow-{uuid4().hex}@example.invalid",
            "password": "PermissionBounds!2026",
            "access_policy": {"MIL": {"allow": ["x" * 129]}},
        },
    )

    assert too_many.status_code == 422, too_many.text
    assert overlong.status_code == 422, overlong.text
    assert overlong_policy.status_code == 422, overlong_policy.text
    assert _snapshot() == before
    with SessionLocal() as db:
        saved = db.get(User, target_id)
        assert saved is not None
        assert saved.name == "Permission bounds target"
        assert saved.extra_permissions == ["finance.view"]


def test_legacy_permission_json_remains_readable_above_new_write_bounds(client, auth_headers):
    legacy_permissions = ["legacy.permission." + ("x" * 130)] + ["legacy.permission"] * 150
    with SessionLocal.begin() as db:
        role = Role(name=f"Legacy permission read {uuid4().hex}", permissions=legacy_permissions)
        db.add(role)
        db.flush()
        user = User(
            name="Legacy permission read",
            email=f"legacy-permission-read-{uuid4().hex}@example.invalid",
            password_hash="unused-test-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=legacy_permissions,
            is_active=True,
        )
        db.add(user)
        db.flush()
        role_id = int(role.id)
        user_id = int(user.id)

    roles = client.get("/api/roles", headers=auth_headers)
    assert roles.status_code == 200, roles.text
    role_payload = next(item for item in roles.json() if item["id"] == role_id)
    assert role_payload["permissions"] == legacy_permissions

    user_response = client.get(f"/api/users/{user_id}", headers=auth_headers)
    assert user_response.status_code == 200, user_response.text
    assert user_response.json()["extra_permissions"] == legacy_permissions


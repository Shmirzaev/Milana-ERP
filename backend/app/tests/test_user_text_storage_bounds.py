from uuid import uuid4

from app.models import AuditLog, User
from app.tests.conftest import TestSessionLocal


def _user_payload(name: str, email: str) -> dict:
    return {"name": name, "email": email, "password": "StorageBound!2026"}


def _user_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(User).count(), db.query(AuditLog).filter_by(entity_type="User").count()


def test_user_name_and_email_storage_boundaries_are_accepted(client, auth_headers):
    email = f"{'a' * 243}@example.com"
    assert len(email) == 255

    response = client.post(
        "/api/users",
        json=_user_payload("N" * 128, email),
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert len(response.json()["name"]) == 128


def test_user_text_overflow_is_rejected_and_preserves_auth_reference_precedence(
    client,
    auth_headers,
):
    before = _user_counts()
    marker = uuid4().hex

    for payload in (
        _user_payload("N" * 129, f"name-{marker}@example.com"),
        _user_payload("Valid Name", f"{'a' * 244}@example.com"),
    ):
        response = client.post("/api/users", json=payload, headers=auth_headers)
        assert response.status_code == 422, response.text
        assert _user_counts() == before

    unauthenticated = client.post(
        "/api/users",
        json=_user_payload("N" * 129, f"unauth-{marker}@example.com"),
    )
    assert unauthenticated.status_code == 401

    missing_role = client.post(
        "/api/users",
        json={**_user_payload("N" * 129, f"role-{marker}@example.com"), "role_id": 2_147_483_647},
        headers=auth_headers,
    )
    assert missing_role.status_code == 404
    assert _user_counts() == before


def test_user_name_overflow_update_is_rejected_without_changing_user(client, auth_headers):
    created = client.post(
        "/api/users",
        json=_user_payload("Bounded User", f"update-{uuid4().hex}@example.com"),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    for changes in (
        {"name": "N" * 129},
        {"email": f"{'a' * 244}@example.com"},
    ):
        response = client.patch(
            f"/api/users/{user_id}",
            json=changes,
            headers=auth_headers,
        )
        assert response.status_code == 422, response.text
    assert client.get(f"/api/users/{user_id}", headers=auth_headers).json()["name"] == "Bounded User"

    missing_user = client.patch(
        "/api/users/2147483647",
        json={"name": "N" * 129},
        headers=auth_headers,
    )
    assert missing_user.status_code == 404

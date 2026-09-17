"""API06: editable profile fields never confer purchasing-price access."""
from types import SimpleNamespace

import pytest

from app.core.deps import user_permissions
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Role, User
from app.services.price_calculation import is_price_purchaser

PERMISSION = "price_calculation.purchasing"


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("name,email", [
    ("Abbosbek", "ordinary@example.com"),
    ("Abbosbek Synthetic", "ordinary@example.com"),
    ("Ordinary", "abbosbek@example.com"),
])
def test_self_profile_changes_do_not_grant_pricing(client, configured, name, email):
    with SessionLocal() as db:
        role = Role(name="Pricing outsider", permissions=[])
        db.add(role)
        db.flush()
        user = User(name="Ordinary", email="ordinary@example.com",
                    password_hash=hash_password("ProfileSecurity!2026"), role_id=role.id,
                    access_policy={"MIL": {"allow": [], "deny": []}} if configured else None)
        db.add(user)
        db.commit()
    login = client.post("/api/auth/token", data={"username": "ordinary@example.com", "password": "ProfileSecurity!2026"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/price-calculation/requests", headers=headers).status_code == 403
    changed = client.patch("/api/auth/me", headers=headers, json={"name": name, "email": email})
    assert changed.status_code == 200, changed.text
    assert PERMISSION not in changed.json()["permissions"]
    assert client.get("/api/price-calculation/requests", headers=headers).status_code == 403
    assert client.patch("/api/price-calculation/requests/999/purchasing", headers=headers,
                        json={"fabric_price": 10}).status_code == 403


@pytest.mark.parametrize("source", ["role", "extra", "policy", "wildcard"])
@pytest.mark.parametrize("denied", [False, True])
def test_explicit_pricing_grants_respect_denials_and_profile_changes(source, denied):
    policy = {"allow": [PERMISSION] if source == "policy" else [],
              "deny": [PERMISSION] if denied else []}
    user = SimpleNamespace(
        role=SimpleNamespace(name="Purchaser", permissions=[PERMISSION] if source == "role" else ["*"] if source == "wildcard" else []),
        extra_permissions=[PERMISSION] if source == "extra" else [],
        access_policy={"MIL": policy}, factory_code="MIL", department=None,
        name="Ordinary", email="ordinary@example.com",
    )
    for name, email in [("Ordinary", "ordinary@example.com"), ("Abbosbek", "abbosbek@example.com")]:
        user.name, user.email = name, email
        assert is_price_purchaser(user) is not denied
        if denied:
            assert PERMISSION not in user_permissions(user)

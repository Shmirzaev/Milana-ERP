from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.deps import user_permissions
from app.core.security import create_access_token
from app.models import Model, PriceCalculationRequest, Role, User
from app.services.price_calculation import is_price_purchaser
from app.tests.conftest import TestSessionLocal


PURCHASING_PERMISSION = "price_calculation.purchasing"
LIST_PATH = "/api/price-calculation/requests"


def _account(*, permissions=(), extra=(), policy=None, factory="MIL"):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        role = Role(name=f"Name authorization {marker}", permissions=list(permissions))
        user = User(
            name="Ordinary employee", email=f"identity-{marker}@example.com",
            password_hash="not-used-by-token-fixture", role=role,
            extra_permissions=list(extra), access_policy=policy, factory_code="MIL",
        )
        model = Model(code=f"IDENTITY-{marker}", name="Confidential price model")
        db.add_all([user, model])
        db.flush()
        request = PriceCalculationRequest(model_id=model.id, created_by_id=user.id, fabric_price=12.5)
        db.add(request)
        db.commit()
        return {
            "id": user.id, "email": user.email, "request_id": request.id,
            "headers": {"Authorization": f"Bearer {create_access_token(user.id, extra={'factory_code': factory})}"},
        }


@pytest.mark.parametrize("policy", [None, {"MIL": {}}], ids=["legacy", "configured"])
@pytest.mark.parametrize("name,email", [
    ("Abbosbek", None),
    ("  aBbOsBeK   Employee  ", None),
    ("Ordinary employee", "abbosbek@identity-test.example.com"),
], ids=["exact-name", "normalized-name-prefix", "email-local-part"])
def test_profile_identity_change_cannot_grant_pricing_access(client, policy, name, email):
    account = _account(policy=policy)
    headers = account["headers"]
    assert client.get(LIST_PATH, headers=headers).status_code == 403
    changed = client.patch(
        "/api/auth/me", headers=headers,
        json={"name": name, "email": email or account["email"]},
    )
    assert changed.status_code == 200, changed.text
    listed = client.get(LIST_PATH, headers=headers)
    updated = client.patch(
        f"{LIST_PATH}/{account['request_id']}/purchasing", headers=headers,
        json={"fabric_price": 99},
    )
    assert (listed.status_code, updated.status_code) == (403, 403)
    assert PURCHASING_PERMISSION not in changed.json()["permissions"]
    with TestSessionLocal() as db:
        request = db.get(PriceCalculationRequest, account["request_id"])
        assert float(request.fabric_price) == 12.5
        assert request.purchasing_updated_by_id is None


@pytest.mark.parametrize("grant", ["role", "extra", "policy", "wildcard"])
def test_explicit_purchasing_grants_survive_profile_changes(client, grant):
    account = _account(
        permissions=[PURCHASING_PERMISSION] if grant == "role" else ["*"] if grant == "wildcard" else [],
        extra=[PURCHASING_PERMISSION] if grant == "extra" else [],
        policy={"MIL": {"allow": [PURCHASING_PERMISSION]}} if grant == "policy" else None,
    )
    for name in ("Abbosbek", "Unrelated new display name"):
        changed = client.patch(
            "/api/auth/me", headers=account["headers"], json={"name": name, "email": account["email"]},
        )
        assert changed.status_code == 200, changed.text
        listed = client.get(LIST_PATH, headers=account["headers"])
        assert listed.status_code == 200, listed.text
        assert account["request_id"] in {row["id"] for row in listed.json()}
        updated = client.patch(
            f"{LIST_PATH}/{account['request_id']}/purchasing", headers=account["headers"],
            json={"fabric_price": 14},
        )
        assert updated.status_code == 200, updated.text


@pytest.mark.parametrize("role_name", [None, "Purchaser", "Admin", "Management", "Super Admin"])
@pytest.mark.parametrize("policy", [None, {"MIL": {}}], ids=["legacy", "configured"])
def test_role_labels_and_identity_do_not_imply_purchasing_permission(role_name, policy):
    user = SimpleNamespace(
        name="Abbosbek Test", email="abbosbek@example.com",
        role=SimpleNamespace(name=role_name, permissions=[]) if role_name else None,
        extra_permissions=[], access_policy=policy, factory_code="MIL", department=None,
    )
    assert PURCHASING_PERMISSION not in user_permissions(user)
    assert not is_price_purchaser(user)


@pytest.mark.parametrize("grant", [PURCHASING_PERMISSION, "*"])
def test_explicit_denial_still_wins_over_grant_and_identity(client, grant):
    account = _account(permissions=[grant], policy={"MIL": {"deny": [PURCHASING_PERMISSION]}})
    changed = client.patch(
        "/api/auth/me", headers=account["headers"], json={"name": "Abbosbek", "email": account["email"]},
    )
    assert changed.status_code == 200
    assert PURCHASING_PERMISSION not in changed.json()["permissions"]
    response = client.patch(
        f"{LIST_PATH}/{account['request_id']}/purchasing", headers=account["headers"], json={"fabric_price": 99},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("secondary_granted", [False, True])
def test_secondary_factory_uses_only_its_explicit_purchasing_grant(client, secondary_granted):
    account = _account(
        permissions=[PURCHASING_PERMISSION], factory="ECO",
        extra=[f"factory:ECO:{PURCHASING_PERMISSION if secondary_granted else 'purchasing.view'}"],
    )
    changed = client.patch(
        "/api/auth/me", headers=account["headers"], json={"name": "Abbosbek", "email": account["email"]},
    )
    assert changed.status_code == 200
    expected = 200 if secondary_granted else 403
    assert client.get(LIST_PATH, headers=account["headers"]).status_code == expected
    response = client.patch(
        f"{LIST_PATH}/{account['request_id']}/purchasing", headers=account["headers"], json={"fabric_price": 99},
    )
    assert response.status_code == expected

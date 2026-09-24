import pytest

from app.core.security import create_access_token
from app.db import session as session_module
from app.models import Role, User


@pytest.mark.parametrize("role_name", ["Storage", "ReadyStorage"])
def test_storage_customer_management(client, role_name):
    with session_module.SessionLocal() as db:
        user = User(name="Customer keeper", email="customer-keeper@example.com", password_hash="unused",
                    role_id=db.query(Role).filter_by(name=role_name).one().id)
        db.add(user)
        db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    assert "sales.customers" in client.get("/api/auth/me", headers=headers).json()["permissions"]
    created = client.post("/api/customers", headers=headers, json={"name": "Storage customer"})
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert client.get(f"/api/customers/{cid}", headers=headers).status_code == 200
    updated = client.patch(f"/api/customers/{cid}", headers=headers, json={"name": "Updated customer"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Updated customer"
    assert client.delete(f"/api/customers/{cid}", headers=headers).status_code == 204
    assert client.get(f"/api/customers/{cid}", headers=headers).status_code == 404

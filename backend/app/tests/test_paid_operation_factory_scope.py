from copy import deepcopy
from uuid import uuid4

from app.models import Department, Model, Role
from app.tests.conftest import TestSessionLocal


PASSWORD = "FactoryScope!2026"


def _create_sewing_master(client, admin_headers, department_code: str) -> dict[str, str]:
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        role_id = db.query(Role.id).filter(Role.name == "Sewing").scalar()
        department_id = db.query(Department.id).filter(Department.code == department_code).scalar()
    assert role_id and department_id
    email = f"{department_code.lower()}.paid.operations.{suffix}@example.com"
    response = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "name": f"{department_code} Sewing Master",
            "email": email,
            "password": PASSWORD,
            "role_id": role_id,
            "department_id": department_id,
            "extra_permissions": ["modeling.models"],
            "is_active": True,
        },
    )
    assert response.status_code == 201, response.text
    login = client.post("/api/auth/token", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_payroll_manager(client, admin_headers, factory_code: str) -> dict[str, str]:
    suffix = uuid4().hex[:8]
    email = f"{factory_code.lower()}.payroll.operations.{suffix}@example.com"
    role = client.post(
        "/api/roles",
        headers=admin_headers,
        json={"name": f"{factory_code} Payroll Operations {suffix}", "permissions": ["payroll.manage", "payroll.view"]},
    )
    assert role.status_code == 201, role.text
    user = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "name": f"{factory_code} Payroll Manager",
            "email": email,
            "password": PASSWORD,
            "role_id": role.json()["id"],
            "factory_code": factory_code,
            "is_active": True,
        },
    )
    assert user.status_code == 201, user.text
    login = client.post("/api/auth/token", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _operation(operation_id: str, factory: str, legacy_source_id: str | None = None) -> dict:
    row = {
        "id": operation_id,
        "selected": True,
        "section": "sewing",
        "code": operation_id.upper(),
        "name": operation_id,
        "rate": "100",
    }
    row["sewingFactory"] = factory
    if legacy_source_id:
        row["legacySourceId"] = legacy_source_id
    return row


def _model_fixture() -> int:
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(
            code=f"OPS-{suffix}",
            name=f"Factory operations {suffix}",
            status="approved",
            details_json={
                "paid_operations": [
                    _operation("current--milana", "milana", "current"),
                    _operation("current--besttex", "besttex", "current"),
                    _operation("current--eco_cotton", "eco_cotton", "current"),
                    _operation("besttex-op", "besttex"),
                ]
            },
        )
        db.add(model)
        db.commit()
        return int(model.id)


def _model_update_payload(model: dict) -> dict:
    return {
        "code": model["code"],
        "name": model["name"],
        "category": model.get("category"),
        "description": model.get("description"),
        "brand_id": model.get("brand_id"),
        "collection_id": model.get("collection_id"),
        "product_type": model.get("product_type"),
        "season": model.get("season"),
        "constructor_employee_id": model.get("constructor_employee_id"),
        "designer_employee_id": model.get("designer_employee_id"),
        "details_json": deepcopy(model["details_json"]),
        "status": model["status"],
        "sam_minutes": model.get("sam_minutes", 0),
    }


def test_sewing_master_sees_only_shared_and_own_factory_operations(client, auth_headers):
    model_id = _model_fixture()
    besttex_headers = _create_sewing_master(client, auth_headers, "BST")

    me = client.get("/api/auth/me", headers=besttex_headers)
    assert me.status_code == 200, me.text
    assert me.json()["department_code"] == "BST"

    detail = client.get(f"/api/models/{model_id}", headers=besttex_headers)
    assert detail.status_code == 200, detail.text
    visible_ids = {row["id"] for row in detail.json()["details_json"]["paid_operations"]}
    assert visible_ids == {"current--besttex", "besttex-op"}

    listed = client.get(f"/api/models?code={detail.json()['code']}", headers=besttex_headers)
    assert listed.status_code == 200, listed.text
    listed_model = next(row for row in listed.json() if int(row["id"]) == model_id)
    assert "details_json" not in listed_model


def test_scoped_update_preserves_hidden_factories_and_rejects_cross_factory_rows(client, auth_headers):
    model_id = _model_fixture()
    besttex_headers = _create_sewing_master(client, auth_headers, "BST")
    scoped_model = client.get(f"/api/models/{model_id}", headers=besttex_headers).json()

    payload = _model_update_payload(scoped_model)
    payload["details_json"]["paid_operations"].append(_operation("forbidden", "milana"))
    rejected = client.patch(f"/api/models/{model_id}", headers=besttex_headers, json=payload)
    assert rejected.status_code == 403, rejected.text

    payload = _model_update_payload(scoped_model)
    next(row for row in payload["details_json"]["paid_operations"] if row["id"] == "besttex-op")["name"] = "Besttex updated"
    updated = client.patch(f"/api/models/{model_id}", headers=besttex_headers, json=payload)
    assert updated.status_code == 200, updated.text
    assert {row["id"] for row in updated.json()["details_json"]["paid_operations"]} == {"current--besttex", "besttex-op"}

    admin_model = client.get(f"/api/models/{model_id}", headers=auth_headers)
    assert admin_model.status_code == 200, admin_model.text
    rows = admin_model.json()["details_json"]["paid_operations"]
    assert {row["id"] for row in rows} == {
        "current--milana",
        "current--besttex",
        "current--eco_cotton",
        "besttex-op",
    }
    assert next(row for row in rows if row["id"] == "besttex-op")["name"] == "Besttex updated"


def test_payroll_manager_can_save_only_own_factory_paid_operations(client, auth_headers):
    model_id = _model_fixture()
    besttex_headers = _create_payroll_manager(client, auth_headers, "BST")

    scoped = client.get(f"/api/models/{model_id}", headers=besttex_headers)
    assert scoped.status_code == 200, scoped.text
    assert {row["id"] for row in scoped.json()["details_json"]["paid_operations"]} == {
        "current--besttex",
        "besttex-op",
    }

    generic_update = client.patch(
        f"/api/models/{model_id}",
        headers=besttex_headers,
        json=_model_update_payload(scoped.json()),
    )
    assert generic_update.status_code == 403

    operations = deepcopy(scoped.json()["details_json"]["paid_operations"])
    next(row for row in operations if row["id"] == "besttex-op")["name"] = "Payroll saved Besttex"
    saved = client.patch(
        f"/api/models/{model_id}/paid-operations",
        headers=besttex_headers,
        json={"paid_operations": operations},
    )
    assert saved.status_code == 200, saved.text
    assert next(
        row for row in saved.json()["details_json"]["paid_operations"] if row["id"] == "besttex-op"
    )["name"] == "Payroll saved Besttex"

    forbidden = client.patch(
        f"/api/models/{model_id}/paid-operations",
        headers=besttex_headers,
        json={"paid_operations": operations + [_operation("forbidden", "milana")]},
    )
    assert forbidden.status_code == 403, forbidden.text

    admin_model = client.get(f"/api/models/{model_id}", headers=auth_headers)
    assert admin_model.status_code == 200, admin_model.text
    rows = admin_model.json()["details_json"]["paid_operations"]
    assert {row["id"] for row in rows} == {
        "current--milana",
        "current--besttex",
        "current--eco_cotton",
        "besttex-op",
    }
    assert next(row for row in rows if row["id"] == "besttex-op")["name"] == "Payroll saved Besttex"

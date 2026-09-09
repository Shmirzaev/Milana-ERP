import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, ModelSize
from app.tests.test_payroll import _create_user_with_permissions
from app.tests.test_process_qr_model_sizes import _model


def test_setup_persists_exact_variant_sizes_and_audit(client, auth_headers):
    mid = _model("QR-SETUP-1", family="QR-SETUP")
    sibling = _model("QR-SETUP-2", ["48", "50"], family="QR-SETUP")
    result = client.post(f"/api/models/{mid}/process-qr-sizes", json={"sizes": [" 52 ", "54"]}, headers=auth_headers)
    assert result.status_code == 201, result.text
    assert result.json() == {"model_id": mid, "sizes": ["52", "54"], "resolution": "own"}
    resolved = client.get(f"/api/models/{mid}/process-qr-sizes", headers=auth_headers)
    assert resolved.json()["sizes"] == ["52", "54"]
    assert resolved.json()["resolution"] == "own"
    detail = client.get(f"/api/models/{mid}", headers=auth_headers).json()
    assert [row["size"] for row in detail["sizes"]] == ["52", "54"]
    with SessionLocal() as db:
        assert [row.size for row in db.query(ModelSize).filter(ModelSize.model_id == sibling).order_by(ModelSize.id)] == ["48", "50"]
        audit = db.query(AuditLog).filter(AuditLog.action == "process_qr_sizes_added", AuditLog.entity_id == mid).one()
        assert audit.old_value_json == {"sizes": []}
        assert audit.new_value_json == {"sizes": ["52", "54"]}


@pytest.mark.parametrize("sizes", [[], [" "], ["S", " s "], ["S"] * 41, ["X" * 33], ["48", ""]])
def test_setup_invalid_payload_is_atomic(client, auth_headers, sizes):
    mid = _model("QR-INVALID-1")
    result = client.post(f"/api/models/{mid}/process-qr-sizes", json={"sizes": sizes}, headers=auth_headers)
    assert result.status_code == 422, result.text
    with SessionLocal() as db:
        assert db.query(ModelSize).filter(ModelSize.model_id == mid).count() == 0
        assert db.query(AuditLog).filter(AuditLog.action == "process_qr_sizes_added", AuditLog.entity_id == mid).count() == 0


def test_setup_rejects_existing_sizes_and_duplicate_submission(client, auth_headers):
    mid = _model("QR-REPEAT-1")
    url = f"/api/models/{mid}/process-qr-sizes"
    assert client.post(url, json={"sizes": ["48", "50"]}, headers=auth_headers).status_code == 201
    for sizes in (["48", "50"], ["52"], ["S", "M"]):
        response = client.post(url, json={"sizes": sizes}, headers=auth_headers)
        assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert [row.size for row in db.query(ModelSize).filter(ModelSize.model_id == mid).order_by(ModelSize.id)] == ["48", "50"]
        assert db.query(AuditLog).filter(AuditLog.action == "process_qr_sizes_added", AuditLog.entity_id == mid).count() == 1


@pytest.mark.parametrize("permissions,factory,status", [
    (["payroll.manage"], "MIL", 201),
    (["payroll.manage"], "BST", 201),
    (["payroll.manage"], "ECO", 201),
    (["modeling.models"], "MIL", 201),
    (["payroll.scan"], "MIL", 403),
    (["payroll.view"], "MIL", 403),
])
def test_setup_uses_effective_permissions_and_shared_standard_catalog(client, auth_headers, permissions, factory, status):
    mid = _model("QR-PERMS-1")
    headers = _create_user_with_permissions(client, auth_headers, email="size-setup@example.com", permissions=permissions, factory_code=factory)
    response = client.post(f"/api/models/{mid}/process-qr-sizes", json={"sizes": ["48", "50"]}, headers=headers)
    assert response.status_code == status, response.text
    with SessionLocal() as db:
        assert db.query(ModelSize).filter(ModelSize.model_id == mid).count() == (2 if status == 201 else 0)


def test_setup_requires_auth_and_does_not_expose_usluga(client, auth_headers):
    mid = _model("QR-AUTH-SETUP-1")
    assert client.post(f"/api/models/{mid}/process-qr-sizes", json={"sizes": ["48"]}).status_code == 401
    service = _model("QR-USL-SETUP-1", scope="usluga")
    for target in (service, 2147483647):
        response = client.post(f"/api/models/{target}/process-qr-sizes?catalog_scope=usluga", json={"sizes": ["48"]}, headers=auth_headers)
        assert response.status_code == 404, response.text
    with SessionLocal() as db:
        assert db.query(ModelSize).filter(ModelSize.model_id.in_([mid, service])).count() == 0

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Department, User
from app.services.audit import log_action


def test_super_data_mutations_are_allowlisted_audited_and_delete_fails_closed(client, auth_headers):
    r = client.post(
        "/api/departments",
        json={"name": "Super Data Temporary", "code": "SDC"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    department_id = r.json()["id"]

    r = client.get("/api/admin/super-data/tables", headers=auth_headers)
    assert r.status_code == 200, r.text
    editable = {
        (table["name"], column["name"])
        for table in r.json()
        for column in table["columns"]
        if column["editable"]
    }
    assert editable == {("departments", "name")}

    r = client.patch(
        f"/api/admin/super-data/tables/departments/rows/{department_id}",
        json={"values": {"code": "BAD"}},
        headers=auth_headers,
    )
    assert r.status_code == 403, r.text

    with SessionLocal() as db:
        admin = db.query(User).filter(User.email == "admin@example.com").one()
        admin_id = admin.id
        original_factory = admin.factory_code
        alternate_factory_headers = {
            "Authorization": f"Bearer {create_access_token(admin.id, extra={'factory_code': 'BST'})}"
        }

    r = client.patch(
        f"/api/admin/super-data/tables/users/rows/{admin_id}",
        json={"values": {"factory_code": "ECO"}},
        headers=alternate_factory_headers,
    )
    assert r.status_code == 403, r.text

    with SessionLocal() as db:
        assert db.get(User, admin_id).factory_code == original_factory

    r = client.patch(
        f"/api/admin/super-data/tables/departments/rows/{department_id}",
        json={"values": {"name": "Super Data Edited"}},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Super Data Edited"

    with SessionLocal() as db:
        audit = (
            db.query(AuditLog)
            .filter_by(action="update", entity_type="SuperData:departments", entity_id=department_id)
            .one()
        )
        assert audit.old_value_json["name"] == "Super Data Temporary"
        assert audit.new_value_json["name"] == "Super Data Edited"

    r = client.get("/api/admin/super-data/tables/departments?q=Super%20Data%20Edited", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(row["id"] == department_id for row in r.json()["rows"])

    r = client.delete(f"/api/admin/super-data/tables/departments/rows/{department_id}", headers=auth_headers)
    assert r.status_code == 409, r.text
    assert "soft-delete" in r.json()["detail"]

    r = client.get("/api/admin/super-data/tables/departments?q=Super%20Data%20Edited", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(row["id"] == department_id for row in r.json()["rows"])

    with SessionLocal() as db:
        assert db.get(Department, department_id) is not None
        assert (
            db.query(AuditLog)
            .filter_by(action="delete", entity_type="SuperData:departments", entity_id=department_id)
            .count()
            == 0
        )



def test_super_data_update_rolls_back_when_audit_fails(client, auth_headers, monkeypatch):
    from app.api.routes import super_data

    r = client.post(
        "/api/departments",
        json={"name": "Super Data Rollback", "code": "SDR"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    department_id = r.json()["id"]

    def fail_audit(*args, **kwargs):
        raise SQLAlchemyError("synthetic audit failure")

    monkeypatch.setattr(super_data, "log_action", fail_audit)
    r = client.patch(
        f"/api/admin/super-data/tables/departments/rows/{department_id}",
        json={"values": {"name": "Must Roll Back"}},
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text

    with SessionLocal() as db:
        assert db.get(Department, department_id).name == "Super Data Rollback"
        assert (
            db.query(AuditLog)
            .filter_by(action="update", entity_type="SuperData:departments", entity_id=department_id)
            .count()
            == 0
        )



def test_super_data_named_department_repair_validates_and_keeps_legacy_patch(client, auth_headers):
    original = client.post(
        "/api/departments",
        json={"name": "Repair Target", "code": "RPT"},
        headers=auth_headers,
    )
    duplicate = client.post(
        "/api/departments",
        json={"name": "Repair Duplicate", "code": "RPD"},
        headers=auth_headers,
    )
    assert original.status_code == 201, original.text
    assert duplicate.status_code == 201, duplicate.text
    department_id = original.json()["id"]
    repair_url = f"/api/admin/super-data/repairs/departments/{department_id}/rename"

    renamed = client.patch(repair_url, json={"name": "  Repaired Name  "}, headers=auth_headers)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Repaired Name"

    blank = client.patch(repair_url, json={"name": "   "}, headers=auth_headers)
    too_long = client.patch(repair_url, json={"name": "N" * 129}, headers=auth_headers)
    extra_field = client.patch(
        repair_url,
        json={"name": "Ignored Extra", "code": "MUTATE"},
        headers=auth_headers,
    )
    duplicate_name = client.patch(
        repair_url,
        json={"name": "Repair Duplicate"},
        headers=auth_headers,
    )
    assert blank.status_code == 422, blank.text
    assert too_long.status_code == 422, too_long.text
    assert extra_field.status_code == 422, extra_field.text
    assert duplicate_name.status_code == 409, duplicate_name.text

    # The former table/row URL stays compatible but accepts only this one
    # named repair and routes through the same validator.
    legacy = client.patch(
        f"/api/admin/super-data/tables/departments/rows/{department_id}",
        json={"values": {"name": "Legacy Compatible Repair"}},
        headers=auth_headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["name"] == "Legacy Compatible Repair"
    rejected_extra_field = client.patch(
        f"/api/admin/super-data/tables/departments/rows/{department_id}",
        json={"values": {"name": "Rejected", "code": "MUTATE"}},
        headers=auth_headers,
    )
    assert rejected_extra_field.status_code == 403, rejected_extra_field.text

    with SessionLocal() as db:
        assert db.get(Department, department_id).name == "Legacy Compatible Repair"
        assert (
            db.query(AuditLog)
            .filter_by(action="update", entity_type="SuperData:departments", entity_id=department_id)
            .count()
            == 2
        )



@pytest.mark.parametrize("operation", ["user_escalation", "audit_tamper", "audit_delete", "department_delete"])
def test_raw_console_mutations_are_rejected_without_changes(client, auth_headers, operation):
    with SessionLocal() as db:
        if operation == "user_escalation":
            target = User(name="Raw target", email="raw-target@example.invalid", password_hash="unused", extra_permissions=[])
            db.add(target); db.flush()
            table, values, expected = "users", {"extra_permissions": ["*"]}, 403
        elif operation.startswith("audit"):
            target = log_action(db, None, "original", "Sec08Test", 1)
            table, values, expected = "audit_logs", {"action": "tampered"}, 403 if operation == "audit_tamper" else 409
        else:
            target = Department(name="Raw delete target", code="RDT")
            db.add(target); db.flush()
            table, values, expected = "departments", {}, 409
        db.commit()
        target_id = target.id
    url = f"/api/admin/super-data/tables/{table}/rows/{target_id}"
    response = client.delete(url, headers=auth_headers) if operation.endswith("delete") else client.patch(url, headers=auth_headers, json={"values": values})
    assert response.status_code == expected, response.text
    with SessionLocal() as db:
        row = db.get({"users": User, "audit_logs": AuditLog, "departments": Department}[table], target_id)
        assert row is not None
        if table == "users":
            assert row.extra_permissions == []
        elif table == "audit_logs":
            assert row.action == "original"

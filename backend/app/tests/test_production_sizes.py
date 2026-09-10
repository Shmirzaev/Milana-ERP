from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.models import AuditLog, Department, ProductionOrder, ProductionOrderItem, User, WorkOrder
from app.tests.conftest import TestSessionLocal


def make_plan():
    with TestSessionLocal() as db:
        po = ProductionOrder(production_no=f"SIZE-{uuid4().hex[:12]}", production_type="branded_stock",
                             model_id=1, planned_quantity=100, status="planning")
        db.add(po)
        db.flush()
        db.add_all([ProductionOrderItem(production_order_id=po.id, model_id=1, color="white", size=size,
                                        planned_quantity=qty, printing_required=False)
                    for size, qty in [("46", 40), ("48", 60)]])
        department = db.query(Department).filter(Department.code == "CUT").one()
        db.add(WorkOrder(production_order_id=po.id, operation="cutting", department_id=department.id,
                         status="ready", planned_input_qty=100, planned_output_qty=100))
        db.commit()
        return po.id


def payload_for(client, headers, pid):
    response = client.get(f"/api/production-orders/{pid}", headers=headers)
    assert response.status_code == 200, response.text
    po = response.json()
    return po, {"items": [{"id": row["id"], "original_size": row["size"], "size": row["size"]} for row in po["items"]]}


def test_size_edit_preserves_plan_and_reaches_cutting_bundles(client, auth_headers):
    pid = make_plan()
    before, payload = payload_for(client, auth_headers, pid)
    payload["items"][0]["size"] = " Free Size "
    payload["items"][1]["size"] = "104"
    response = client.patch(f"/api/production-orders/{pid}/sizes", json=payload, headers=auth_headers)
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["planned_quantity"] == before["planned_quantity"] == 100
    for old, new in zip(before["items"], after["items"]):
        assert {k: v for k, v in old.items() if k != "size"} == {k: v for k, v in new.items() if k != "size"}
    assert [row["size"] for row in after["items"]] == ["Free Size", "104"]
    with TestSessionLocal() as db:
        audit = db.query(AuditLog).filter_by(action="update_sizes", entity_id=pid).one()
        assert audit.user_id == 1
        assert [row["size"] for row in audit.old_value_json["items"]] == ["46", "48"]
    cutting = next(wo for wo in after["work_orders"] if wo["operation"] == "cutting")
    result = client.post("/api/cutting/records", headers=auth_headers, json={
        "work_order_id": cutting["id"], "input_quantity": 0, "cut_pieces": 100, "passed_pieces": 100,
        "bundles": [{"color": row["color"], "size": row["size"], "quantity": row["planned_quantity"], "count": 1}
                    for row in after["items"]],
    })
    assert result.status_code == 201, result.text
    from app.models import Bundle
    with TestSessionLocal() as db:
        bundles = db.query(Bundle).filter_by(production_order_id=pid).all()
        assert sorted((b.size, b.quantity) for b in bundles) == [("104", 60), ("Free Size", 40)]
    _, retry = payload_for(client, auth_headers, pid)
    retry["items"][0]["size"] = "50"
    assert client.patch(f"/api/production-orders/{pid}/sizes", json=retry, headers=auth_headers).status_code == 409


@pytest.mark.parametrize("invalid", ["duplicate_size", "blank", "too_long", "duplicate_id", "foreign_id", "missing_row", "stale", "quantity"])
def test_invalid_size_edits_are_atomic(client, auth_headers, invalid):
    pid = make_plan()
    before, payload = payload_for(client, auth_headers, pid)
    first, second = payload["items"]
    first["size"] = "50"
    if invalid == "duplicate_size":
        second["size"] = "50"
    elif invalid == "blank":
        second["size"] = "   "
    elif invalid == "too_long":
        second["size"] = "X" * 33
    elif invalid == "duplicate_id":
        second["id"] = first["id"]
    elif invalid == "foreign_id":
        other, _ = payload_for(client, auth_headers, make_plan())
        second["id"] = other["items"][0]["id"]
    elif invalid == "missing_row":
        payload["items"].pop()
    elif invalid == "stale":
        second["original_size"] = "52"
    elif invalid == "quantity":
        first["planned_quantity"] = 999
    response = client.patch(f"/api/production-orders/{pid}/sizes", json=payload, headers=auth_headers)
    assert response.status_code in (400, 409, 422), response.text
    after, _ = payload_for(client, auth_headers, pid)
    assert before["items"] == after["items"]
    with TestSessionLocal() as db:
        assert not db.query(AuditLog).filter_by(action="update_sizes", entity_id=pid).first()


@pytest.mark.parametrize("locked", ["cutting", "completed", "cancelled", "usluga", "completed_row", "issued_label"])
def test_used_or_closed_size_plans_are_locked(client, auth_headers, locked):
    pid = make_plan()
    before, payload = payload_for(client, auth_headers, pid)
    with TestSessionLocal() as db:
        po = db.get(ProductionOrder, pid)
        if locked == "cutting":
            db.query(WorkOrder).filter_by(production_order_id=pid).one().status = "in_progress"
        elif locked in ("completed", "cancelled"):
            po.status = locked
        elif locked == "usluga":
            po.source_type = "usluga"
        elif locked == "completed_row":
            db.get(ProductionOrderItem, payload["items"][0]["id"]).completed_quantity = 1
        else:
            from app.models.payroll import PayrollQrLabel
            db.add(PayrollQrLabel(label_uid=uuid4().hex, production_order_id=pid, size="46"))
        db.commit()
    payload["items"][0]["size"] = "50"
    response = client.patch(f"/api/production-orders/{pid}/sizes", json=payload, headers=auth_headers)
    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        assert [row.size for row in db.query(ProductionOrderItem).filter_by(production_order_id=pid).order_by(ProductionOrderItem.id)] == ["46", "48"]


@pytest.mark.parametrize("email,expected", [("planning@example.com", 200), ("cutting@example.com", 403)])
def test_size_edit_requires_planning_permission(client, auth_headers, email, expected):
    pid = make_plan()
    _, payload = payload_for(client, auth_headers, pid)
    with TestSessionLocal() as db:
        user = db.query(User).filter_by(email=email).one()
        headers = {"Authorization": "Bearer " + create_access_token(user.id, extra={"factory_code": "MIL"})}
    payload["items"][0]["size"] = "50"
    response = client.patch(f"/api/production-orders/{pid}/sizes", json=payload, headers=headers)
    assert response.status_code == expected, response.text


def test_stale_second_editor_cannot_overwrite_saved_sizes(client, auth_headers):
    pid = make_plan()
    _, payload = payload_for(client, auth_headers, pid)
    payload["items"][0]["size"] = "50"
    assert client.patch(f"/api/production-orders/{pid}/sizes", json=payload, headers=auth_headers).status_code == 200
    payload["items"][0]["size"] = "52"
    assert client.patch(f"/api/production-orders/{pid}/sizes", json=payload, headers=auth_headers).status_code == 409

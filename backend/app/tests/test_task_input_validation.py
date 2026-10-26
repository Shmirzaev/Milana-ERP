from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.schemas import Model, ProductionOrder, SalesOrder, Task
from app.tests.test_task_assignment_authorization import _actor, _snapshot


@pytest.mark.parametrize("field,value", [
    ("title", "   "),
    ("status", "done-ish"),
    ("priority", "critical"),
    ("due_date", 1_700_000_000),
    ("entity_type", "SalesOrder"),
    ("entity_id", 42),
])
def test_create_rejects_invalid_task_fields_without_writes(client, field, value):
    _, headers = _actor()
    with SessionLocal() as db:
        before = db.query(Task).count()
    response = client.post("/api/tasks", headers=headers, json={"title": "Task", field: value})
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(Task).count() == before


@pytest.mark.parametrize("field,value", [
    ("title", None),
    ("status", None),
    ("status", "done-ish"),
    ("priority", "critical"),
    ("due_date", "1700000000"),
    ("entity_type", "SalesOrder"),
    ("entity_id", 42),
])
def test_patch_rejects_invalid_task_fields_without_writes(client, field, value):
    actor, headers = _actor()
    created = client.post("/api/tasks", headers=headers, json={"title": "Task"})
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    before = _snapshot(tid)
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={field: value})
    assert response.status_code == 422, response.text
    assert _snapshot(tid) == before


def test_create_rejects_unsupported_and_missing_references(client):
    _, headers = _actor()
    unsupported = client.post("/api/tasks", headers=headers, json={
        "title": "Bad type", "entity_type": "FactorySecret", "entity_id": 1,
    })
    missing = client.post("/api/tasks", headers=headers, json={
        "title": "Missing order", "entity_type": "SalesOrder", "entity_id": 2_000_000_000,
    })
    assert unsupported.status_code == 422, unsupported.text
    assert missing.status_code == 404, missing.text


def test_patch_rejects_missing_reference_and_keeps_task(client):
    _, headers = _actor()
    tid = client.post("/api/tasks", headers=headers, json={"title": "Task"}).json()["id"]
    before = _snapshot(tid)
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={
        "entity_type": "sales_order", "entity_id": 2_000_000_000,
    })
    assert response.status_code == 404, response.text
    assert _snapshot(tid) == before


def test_valid_sales_order_reference_survives_create_and_patch(client):
    _, headers = _actor()
    with SessionLocal() as db:
        order = SalesOrder(order_no=f"SO-API02-{uuid4().hex[:10]}")
        db.add(order)
        db.commit()
        order_id = order.id
    response = client.post("/api/tasks", headers=headers, json={
        "title": "Follow up", "entity_type": "sales_order", "entity_id": order_id,
    })
    assert response.status_code == 201, response.text
    tid = response.json()["id"]
    patched = client.patch(f"/api/tasks/{tid}", headers=headers, json={"title": "Follow up today"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["entity_id"] == order_id


def _eco_production_order() -> int:
    with SessionLocal() as db:
        model_id = db.query(Model.id).first()[0]
        order = ProductionOrder(
            production_no=f"PO-API02-{uuid4().hex[:10]}",
            model_id=model_id, production_type="client_order", source_type="usluga", planned_quantity=1,
        )
        db.add(order)
        db.commit()
        return order.id


def test_reference_requires_actor_read_permission_and_factory(client):
    order_id = _eco_production_order()
    _, no_read = _actor()
    _, wrong_factory = _actor(("planning.view",), factory="MIL")
    body = {"title": "Restricted", "entity_type": "ProductionOrder", "entity_id": order_id}
    assert client.post("/api/tasks", headers=no_read, json=body).status_code == 403
    assert client.post("/api/tasks", headers=wrong_factory, json=body).status_code == 403


def test_reference_requires_assignee_read_access(client):
    order_id = _eco_production_order()
    _, manager = _actor(("tasks.manage", "planning.view"), factory="ECO")
    assignee_id, _ = _actor(factory="ECO")
    response = client.post("/api/tasks", headers=manager, json={
        "title": "Not visible", "assigned_to": assignee_id,
        "entity_type": "ProductionOrder", "entity_id": order_id,
    })
    assert response.status_code == 422, response.text


def test_patch_reference_and_reassignment_require_access(client):
    order_id = _eco_production_order()
    _, wrong_factory = _actor(("tasks.manage", "planning.view"), factory="MIL")
    _, manager = _actor(("tasks.manage", "planning.view"), factory="ECO")
    assignee_id, _ = _actor(factory="ECO")
    tid = client.post("/api/tasks", headers=manager, json={"title": "Task"}).json()["id"]
    before = _snapshot(tid)
    reference = {"entity_type": "ProductionOrder", "entity_id": order_id}
    assert client.patch(f"/api/tasks/{tid}", headers=wrong_factory, json=reference).status_code == 403
    assert _snapshot(tid) == before
    attached = client.patch(f"/api/tasks/{tid}", headers=manager, json=reference)
    assert attached.status_code == 200, attached.text
    before_reassign = _snapshot(tid)
    denied = client.patch(f"/api/tasks/{tid}", headers=manager, json={"assigned_to": assignee_id})
    assert denied.status_code == 422, denied.text
    assert _snapshot(tid) == before_reassign


def test_broadcast_reference_rejects_inaccessible_recipient_before_writes(client, monkeypatch):
    monkeypatch.setenv("ERP_MCP_MAX_BULK_RECIPIENTS", "250")
    order_id = _eco_production_order()
    _, manager = _actor(("tasks.manage", "planning.view"), factory="ECO")
    with SessionLocal() as db:
        before = db.query(Task).count()
    response = client.post("/api/tasks", headers=manager, json={
        "title": "Broadcast", "assigned_to": -1,
        "entity_type": "ProductionOrder", "entity_id": order_id,
    })
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(Task).count() == before


def test_valid_task_values_and_reopen_still_work(client):
    _, headers = _actor()
    created = client.post("/api/tasks", headers=headers, json={
        "title": "Scheduled", "status": "in_progress", "priority": "urgent", "due_date": "2026-11-05T09:00:00",
    })
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    assert client.post(f"/api/tasks/{tid}/complete", headers=headers).status_code == 200
    reopened = client.patch(f"/api/tasks/{tid}", headers=headers, json={"status": "in_progress"})
    assert reopened.status_code == 200 and reopened.json()["completed_at"] is None


def test_unrelated_edit_preserves_legacy_partial_reference(client):
    actor_id, headers = _actor()
    with SessionLocal() as db:
        task = Task(title="Legacy partial", assigned_to=actor_id, created_by=actor_id,
                    status="pending", priority="medium", entity_type="SalesOrder")
        db.add(task)
        db.commit()
        tid = task.id
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={"title": "Still editable"})
    assert response.status_code == 200, response.text
    assert response.json()["entity_type"] == "SalesOrder" and response.json()["entity_id"] is None


def test_invalid_status_filter_is_rejected(client):
    _, headers = _actor()
    response = client.get("/api/tasks?status=done-ish", headers=headers)
    assert response.status_code == 422, response.text

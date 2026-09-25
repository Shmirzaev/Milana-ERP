from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Role, SalesOrder, Task, User
from app.schemas.tasks import TaskIn


def _actor():
    with SessionLocal() as db:
        role = Role(
            name=f"Task validation {uuid4().hex}",
            permissions=["planning.view", "finance.view"],
        )
        user = User(
            name="Task validation actor",
            email=f"task-validation-{uuid4().hex}@example.com",
            password_hash="unused-token-fixture",
            role=role,
            factory_code="MIL",
        )
        db.add(user)
        db.commit()
        return user.id, {"Authorization": f"Bearer {create_access_token(user.id, {'factory_code': 'MIL'})}"}


def _snapshot(task_id):
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        return {
            "task": {column.name: getattr(task, column.name) for column in Task.__table__.columns},
            "audits": db.query(AuditLog).count(),
        }


def _task_count():
    with SessionLocal() as db:
        return db.query(Task).count()


def _audit_count():
    with SessionLocal() as db:
        return db.query(AuditLog).count()


def _create(client, headers, **payload):
    response = client.post("/api/tasks", headers=headers, json={"title": "Valid task", **payload})
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize("field,value", [
    ("status", "bogus"), ("priority", "bogus"), ("title", "   "), ("title", "x" * 256),
    ("due_date", 1_700_000_000), ("due_date", "1700000000.0"), ("due_date", "not-a-date"),
    ("entity_id", 0), ("entity_id", 2_147_483_648), ("entity_type", "customer"),
])
def test_invalid_create_is_422_without_persisting(client, field, value):
    _, headers = _actor()
    before = (_task_count(), _audit_count())
    response = client.post("/api/tasks", headers=headers, json={"title": "Valid task", field: value})
    assert response.status_code == 422, response.text
    assert (_task_count(), _audit_count()) == before


@pytest.mark.parametrize("field", ["title", "status", "priority"])
def test_explicit_null_required_patch_field_is_rejected_without_changes(client, field):
    creator, headers = _actor()
    task_id = _create(client, headers)
    before = _snapshot(task_id)
    response = client.patch(f"/api/tasks/{task_id}", headers=headers, json={field: None})
    assert response.status_code == 422, response.text
    assert _snapshot(task_id) == before


def test_patch_omitted_fields_stay_unchanged_and_optional_fields_can_clear(client):
    _, headers = _actor()
    task_id = _create(client, headers, description="keep", due_date="2026-09-20", status="in_progress")
    response = client.patch(f"/api/tasks/{task_id}", headers=headers, json={"description": None, "due_date": None})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Valid task" and body["status"] == "in_progress"
    assert body["description"] is None and body["due_date"] is None


def test_task_description_utf8_boundary_and_oversized_create_leave_no_writes(client):
    _, headers = _actor()
    boundary = "🙂" * 4096  # 16 KiB as UTF-8, although only 4096 characters.
    task_id = _create(client, headers, description=boundary)
    with SessionLocal() as db:
        assert db.get(Task, task_id).description == boundary

    before = (_task_count(), _audit_count())
    response = client.post(
        "/api/tasks", headers=headers,
        json={"title": "Oversized task", "description": boundary + "x"},
    )
    assert response.status_code == 422, response.text
    assert (_task_count(), _audit_count()) == before


def test_task_description_oversized_patch_leaves_task_and_audit_unchanged(client):
    _, headers = _actor()
    task_id = _create(client, headers, description="Before")
    before = _snapshot(task_id)
    response = client.patch(
        f"/api/tasks/{task_id}", headers=headers,
        json={"title": "Would change", "description": "🙂" * 4096 + "x"},
    )
    assert response.status_code == 422, response.text
    assert _snapshot(task_id) == before


def test_task_unchanged_legacy_description_is_not_rewritten_to_audit_json(client):
    creator, headers = _actor()
    legacy = "legacy" * 4000
    with SessionLocal() as db:
        task = Task(
            title="Legacy task", description=legacy, created_by=creator,
            assigned_to=creator, status="pending", priority="medium",
        )
        db.add(task)
        db.commit()
        task_id = task.id

    response = client.patch(
        f"/api/tasks/{task_id}", headers=headers,
        json={"title": "Edited title", "description": legacy},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(Task, task_id).description == legacy
        audit = db.query(AuditLog).filter_by(entity_type="Task", entity_id=task_id).order_by(AuditLog.id.desc()).first()
        assert audit.new_value_json == {"title": "Edited title"}

    before = _snapshot(task_id)
    response = client.patch(
        f"/api/tasks/{task_id}", headers=headers,
        json={"description": legacy + "x"},
    )
    assert response.status_code == 422, response.text
    assert _snapshot(task_id) == before


@pytest.mark.parametrize("field,value", [
    ("status", "bogus"), ("priority", "bogus"), ("title", "x" * 256),
    ("due_date", 1_700_000_000), ("entity_id", 2_147_483_648), ("entity_type", "customer"),
    ("entity_type", "x" * 65), ("entity_type", " "),
])
def test_invalid_patch_is_422_without_changes_or_audit(client, field, value):
    _, headers = _actor()
    task_id = _create(client, headers)
    before = _snapshot(task_id)
    response = client.patch(f"/api/tasks/{task_id}", headers=headers, json={field: value})
    assert response.status_code == 422, response.text
    assert _snapshot(task_id) == before


def test_legacy_orphan_reference_allows_unrelated_patch_but_reference_change_requires_pair(client):
    creator, headers = _actor()
    with SessionLocal() as db:
        task = Task(title="Legacy orphan", created_by=creator, assigned_to=creator, status="pending", priority="medium", entity_id=123)
        db.add(task)
        db.commit()
        task_id = task.id
    response = client.patch(f"/api/tasks/{task_id}", headers=headers, json={"status": "in_progress", "title": "Updated orphan"})
    assert response.status_code == 200, response.text
    response = client.patch(f"/api/tasks/{task_id}", headers=headers, json={"entity_type": "WorkOrder"})
    assert response.status_code == 404, response.text
    clean_id = _create(client, headers)
    response = client.patch(f"/api/tasks/{clean_id}", headers=headers, json={"entity_type": "WorkOrder"})
    assert response.status_code == 422, response.text


def test_valid_date_only_and_timezone_dates_are_accepted(client):
    _, headers = _actor()
    for due_date in ("2026-09-20", "2026-09-20T12:00:00+05:00"):
        response = client.post("/api/tasks", headers=headers, json={"title": "Date task", "due_date": due_date})
        assert response.status_code == 201, response.text


def test_create_and_patch_reference_pair_requires_positive_id(client):
    _, headers = _actor()
    for payload in ({"entity_id": 123}, {"entity_type": "WorkOrder"}):
        response = client.post("/api/tasks", headers=headers, json={"title": "Reference", **payload})
        assert response.status_code == 422, response.text
    with SessionLocal() as db:
        order = SalesOrder(order_no=f"TASK-{uuid4().hex}")
        db.add(order)
        db.commit()
        order_id = order.id
    task_id = _create(client, headers, entity_type="Sales_Order", entity_id=order_id)
    with SessionLocal() as db:
        assert db.get(Task, task_id).entity_type == "Sales_Order"
    response = client.patch(f"/api/tasks/{task_id}", headers=headers, json={"entity_id": order_id})
    assert response.status_code == 200, response.text


def test_unsupported_new_task_target_keeps_unauthenticated_precedence(client):
    before = (_task_count(), _audit_count())
    response = client.post("/api/tasks", json={
        "title": "Invalid target", "entity_type": "customer", "entity_id": 1,
    })
    assert response.status_code == 401, response.text
    assert (_task_count(), _audit_count()) == before


def test_legacy_unsupported_task_target_remains_readable(client):
    creator, headers = _actor()
    with SessionLocal() as db:
        task = Task(
            title="Legacy target", created_by=creator, assigned_to=creator,
            status="pending", priority="medium", entity_type="customer", entity_id=1,
        )
        db.add(task)
        db.commit()
        task_id = task.id
    response = client.get("/api/tasks?scope=created", headers=headers)
    assert response.status_code == 200, response.text
    returned = next(row for row in response.json() if row["id"] == task_id)
    assert returned["entity_type"] == "customer"


def test_reference_target_must_exist_on_create_and_patch(client):
    _, headers = _actor()
    missing = client.post("/api/tasks", headers=headers, json={
        "title": "Missing target", "entity_type": "WorkOrder", "entity_id": 123,
    })
    assert missing.status_code == 404, missing.text
    task_id = _create(client, headers)
    missing_patch = client.patch(f"/api/tasks/{task_id}", headers=headers, json={
        "entity_type": "Invoice", "entity_id": 123,
    })
    assert missing_patch.status_code == 404, missing_patch.text


def test_postgres_int4_upper_entity_id_is_accepted_structurally():
    payload = TaskIn(
        title="Upper bound reference",
        entity_type="WorkOrder",
        entity_id=2_147_483_647,
    )
    assert payload.entity_id == 2_147_483_647

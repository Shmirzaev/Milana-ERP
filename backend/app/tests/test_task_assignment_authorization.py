"""Task creators may edit their tasks, but do not acquire assignment authority."""
from uuid import uuid4

import pytest

from app.api.routes import tasks
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Notification, Role, Task, User


def _actor(permissions=(), *, role_name=None, policy=None, factory="MIL", extra=(), selected=None, active=True):
    with SessionLocal() as db:
        role = db.query(Role).filter_by(name=role_name).first() if role_name else None
        if role is None:
            role = Role(name=role_name or f"Task fixture {uuid4().hex}", permissions=list(permissions))
        else:
            role.permissions = list(permissions)
        user = User(name="Synthetic task actor", email=f"task-{uuid4().hex}@example.com", password_hash="unused-token-fixture",
                    role=role, factory_code=factory, extra_permissions=list(extra), access_policy=policy, is_active=active)
        db.add(user)
        db.commit()
        return user.id, {"Authorization": f"Bearer {create_access_token(user.id, {'factory_code': selected or factory})}"}


def _task(creator, assignee):
    with SessionLocal() as db:
        task = Task(title="Synthetic task", description="Preserved task description", created_by=creator,
                    assigned_to=assignee, status="pending", priority="medium", entity_type="WorkOrder", entity_id=123)
        db.add(task)
        db.commit()
        return task.id


def _snapshot(tid):
    with SessionLocal() as db:
        task = db.get(Task, tid)
        return {
            "task": {column.name: getattr(task, column.name) for column in Task.__table__.columns},
            "tasks": db.query(Task).count(),
            "notifications": db.query(Notification).count(),
            "audits": db.query(AuditLog).count(),
        }


@pytest.mark.parametrize("factory", ["MIL", "ECO"])
def test_creator_cannot_bypass_creation_assignment_rule_through_patch(client, factory):
    creator, headers = _actor()
    target, _ = _actor(factory=factory)
    created = client.post("/api/tasks", headers=headers, json={"title": "Self task"})
    assert created.status_code == 201 and created.json()["assigned_to"] == creator
    tid = created.json()["id"]
    before = _snapshot(tid)
    denied_create = client.post("/api/tasks", headers=headers, json={"title": "Forbidden", "assigned_to": target})
    denied_patch = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": target, "title": "Must not save"})
    assert denied_create.status_code == denied_patch.status_code == 403
    assert denied_patch.json() == denied_create.json()
    assert _snapshot(tid) == before


def test_creator_cannot_unassign_without_assignment_authority(client):
    creator, headers = _actor()
    tid = _task(creator, creator)
    before = _snapshot(tid)
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": None})
    assert response.status_code == 403, response.text
    assert _snapshot(tid) == before


@pytest.mark.parametrize("mode", ["omitted", "unchanged_other", "unchanged_null"])
def test_creator_normal_edits_keep_omitted_and_unchanged_assignee(client, mode):
    creator, headers = _actor()
    other, _ = _actor()
    assignee = None if mode == "unchanged_null" else other
    tid = _task(creator, assignee)
    before = _snapshot(tid)
    payload = {"title": "Edited by creator", "description": None, "priority": "high"}
    if mode != "omitted":
        payload["assigned_to"] = assignee
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned_to"] == assignee and body["title"] == payload["title"]
    assert body["entity_type"] == "WorkOrder" and body["entity_id"] == 123
    after = _snapshot(tid)
    assert after["notifications"] == before["notifications"]
    assert after["audits"] == before["audits"] + 1


def test_creator_can_assign_own_existing_task_to_self(client):
    creator, headers = _actor()
    other, _ = _actor()
    tid = _task(creator, other)
    before = _snapshot(tid)
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": creator})
    assert response.status_code == 200 and response.json()["assigned_to"] == creator
    after = _snapshot(tid)
    assert after["notifications"] == before["notifications"] + 1
    assert after["audits"] == before["audits"] + 1


@pytest.mark.parametrize(("permissions", "role_name"), [
    (("tasks.manage",), None), (("management.approve",), None), (("*",), None), ((), "Admin"), ((), "Management"),
])
def test_existing_manager_rules_allow_assignment_and_notification(client, permissions, role_name):
    manager, headers = _actor(permissions, role_name=role_name)
    first, _ = _actor()
    target, _ = _actor(factory="ECO")
    created = client.post("/api/tasks", headers=headers, json={"title": "Manager assignment", "assigned_to": first})
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    before = _snapshot(tid)
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": target})
    assert response.status_code == 200, response.text
    assert response.json()["assigned_to"] == target and response.json()["created_by"] == manager
    after = _snapshot(tid)
    assert after["notifications"] == before["notifications"] + 1
    assert after["audits"] == before["audits"] + 1
    with SessionLocal() as db:
        notification = db.query(Notification).order_by(Notification.id.desc()).first()
        assert notification.user_id == target and notification.title == "Task reassigned to you: Manager assignment"


def test_manager_can_unassign_without_new_assignee_notification(client):
    manager, headers = _actor(("tasks.manage",))
    target, _ = _actor()
    tid = _task(manager, target)
    before = _snapshot(tid)
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": None})
    assert response.status_code == 200 and response.json()["assigned_to"] is None
    after = _snapshot(tid)
    assert after["notifications"] == before["notifications"]
    assert after["audits"] == before["audits"] + 1


@pytest.mark.parametrize("role_name", [None, "Management"])
def test_explicit_assignment_denial_is_not_bypassed_by_creator(client, role_name):
    creator, headers = _actor(("*",), role_name=role_name, policy={"MIL": {"deny": ["tasks.manage"]}})
    target, _ = _actor()
    tid = _task(creator, creator)
    before = _snapshot(tid)
    assert client.post("/api/tasks", headers=headers, json={"title": "Denied", "assigned_to": target}).status_code == 403
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": target})
    assert response.status_code == 403, response.text
    assert _snapshot(tid) == before


@pytest.mark.parametrize("secondary_permission", ["tasks.manage", "cutting.records"])
def test_assignment_uses_effective_selected_factory_permissions(client, secondary_permission):
    creator, headers = _actor(("tasks.manage",), extra=[f"factory:ECO:{secondary_permission}"], selected="ECO")
    target, _ = _actor(factory="ECO")
    tid = _task(creator, creator)
    before = _snapshot(tid)
    expected = 200 if secondary_permission == "tasks.manage" else 403
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": target})
    assert response.status_code == expected, response.text
    if expected == 403:
        assert _snapshot(tid) == before
    else:
        assert response.json()["assigned_to"] == target


@pytest.mark.parametrize("assigned_to", [0, -1, 2_000_000_000])
def test_manager_changed_assignee_requires_existing_single_user(client, assigned_to):
    creator, headers = _actor(("tasks.manage",))
    tid = _task(creator, creator)
    before = _snapshot(tid)
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": assigned_to, "title": "Not saved"})
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Assigned user not found"}
    assert _snapshot(tid) == before


def test_nonmanager_reference_authorization_precedes_lookup(client):
    creator, headers = _actor()
    tid = _task(creator, creator)
    before = _snapshot(tid)
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": 2_000_000_000})
    assert response.status_code == 403, response.text
    assert _snapshot(tid) == before


def test_existing_inactive_assignee_policy_is_not_changed(client):
    creator, headers = _actor(("tasks.manage",))
    inactive, _ = _actor(active=False)
    created = client.post("/api/tasks", headers=headers, json={"title": "Existing policy", "assigned_to": inactive})
    assert created.status_code == 201, created.text
    tid = _task(creator, creator)
    changed = client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": inactive})
    assert changed.status_code == 200 and changed.json()["assigned_to"] == inactive


@pytest.mark.parametrize("payload", [{"title": "Forbidden"}, {"assigned_to": None}, {"same_assignee": True}])
def test_assignee_only_remains_status_only_even_for_unchanged_assignment(client, payload):
    creator, _ = _actor()
    assignee, headers = _actor()
    tid = _task(creator, assignee)
    before = _snapshot(tid)
    body = {"assigned_to": assignee} if "same_assignee" in payload else payload
    response = client.patch(f"/api/tasks/{tid}", headers=headers, json=body)
    assert response.status_code == 403 and response.json() == {"detail": "Assignees can only change status"}
    assert _snapshot(tid) == before


def test_assignee_status_and_existing_visibility_rules_remain(client):
    creator, creator_headers = _actor()
    assignee, assignee_headers = _actor()
    _, outsider_headers = _actor()
    tid = _task(creator, assignee)
    for headers in (creator_headers, assignee_headers):
        assert client.get(f"/api/tasks/{tid}", headers=headers).status_code == 200
    before = _snapshot(tid)
    assert client.get(f"/api/tasks/{tid}", headers=outsider_headers).status_code == 403
    assert client.patch(f"/api/tasks/{tid}", headers=outsider_headers, json={"status": "completed"}).status_code == 403
    assert client.get("/api/tasks?scope=all", headers=creator_headers).status_code == 403
    assert _snapshot(tid) == before
    assert [row["id"] for row in client.get("/api/tasks?scope=created", headers=creator_headers).json()] == [tid]
    assert [row["id"] for row in client.get("/api/tasks", headers=assignee_headers).json()] == [tid]
    completed = client.patch(f"/api/tasks/{tid}", headers=assignee_headers, json={"status": "completed"})
    assert completed.status_code == 200 and completed.json()["completed_at"]
    reopened = client.patch(f"/api/tasks/{tid}", headers=assignee_headers, json={"status": "in_progress"})
    assert reopened.status_code == 200 and reopened.json()["completed_at"] is None
    assert client.get("/api/tasks/open-count", headers=assignee_headers).json() == {"count": 1}


@pytest.mark.parametrize("assigned", [None, 0, "omitted"])
def test_create_default_assignment_remains_self(client, assigned):
    actor, headers = _actor()
    payload = {"title": "Defaults unchanged"}
    if assigned != "omitted":
        payload["assigned_to"] = assigned
    response = client.post("/api/tasks", headers=headers, json=payload)
    assert response.status_code == 201 and response.json()["assigned_to"] == actor


def test_create_broadcast_mode_and_permissions_remain(client):
    _, denied_headers = _actor()
    _, manager_headers = _actor(("tasks.manage",))
    before_tasks = _task(None, None)
    before = _snapshot(before_tasks)
    assert client.post("/api/tasks", headers=denied_headers, json={"title": "Broadcast", "assigned_to": -1}).status_code == 403
    assert _snapshot(before_tasks) == before
    response = client.post("/api/tasks", headers=manager_headers, json={"title": "Broadcast", "assigned_to": -1})
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        active_ids = {row.id for row in db.query(User).filter_by(is_active=True)}
        assert {row.assigned_to for row in db.query(Task).filter_by(title="Broadcast")} == active_ids


def test_assignment_failure_rolls_back_notification_task_and_audit(client, monkeypatch):
    creator, headers = _actor(("tasks.manage",))
    target, _ = _actor()
    tid = _task(creator, creator)
    before = _snapshot(tid)
    original = tasks.log_action

    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic task audit failure")

    monkeypatch.setattr(tasks, "log_action", fail_after_audit)
    with pytest.raises(RuntimeError, match="Synthetic task audit failure"):
        client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": target})
    assert _snapshot(tid) == before
    monkeypatch.setattr(tasks, "log_action", original)
    assert client.patch(f"/api/tasks/{tid}", headers=headers, json={"assigned_to": target}).status_code == 200
    after = _snapshot(tid)
    assert after["notifications"] == before["notifications"] + 1 and after["audits"] == before["audits"] + 1


def test_task_patch_still_requires_authentication_and_handles_missing_task(client):
    _, headers = _actor()
    path = "/api/tasks/2000000000"
    assert client.patch(path, json={"status": "completed"}).status_code == 401
    assert client.patch(path, headers=headers, json={"status": "completed"}).status_code == 404

"""Notification reads and acknowledgements remain private and bounded."""

import pytest
from fastapi import HTTPException

from app.db.session import SessionLocal
from app.models import Notification
from app.api.routes.notifications import NotificationSendIn, _resolve_recipients
from app.tests.test_task_assignment_authorization import _actor


def _notification(user_id, *, read=False):
    with SessionLocal() as db:
        row = Notification(user_id=user_id, title="Synthetic notice", is_read=read)
        db.add(row)
        db.commit()
        return row.id


@pytest.mark.parametrize("limit,expected", [(-1, 1), (0, 0), (20, 20), (5000, 500)])
def test_notification_list_uses_shared_page_bounds(client, limit, expected):
    user_id, headers = _actor()
    other_id, _ = _actor()
    with SessionLocal() as db:
        db.add_all([Notification(user_id=user_id, title=f"Notice {index}") for index in range(501)])
        db.add(Notification(user_id=other_id, title="Private other notice"))
        db.commit()
    response = client.get(f"/api/notifications?limit={limit}", headers=headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == expected
    assert all(row["user_id"] == user_id for row in rows)
    assert [row["id"] for row in rows] == sorted((row["id"] for row in rows), reverse=True)


def test_notification_count_and_read_operations_are_user_scoped(client):
    user_id, headers = _actor()
    other_id, other_headers = _actor()
    first = _notification(user_id)
    second = _notification(user_id)
    _notification(user_id, read=True)
    other = _notification(other_id)
    assert client.get("/api/notifications/unread-count", headers=headers).json() == {"count": 2}
    denied = client.post(f"/api/notifications/{other}/read", headers=headers)
    assert denied.status_code == 404
    first_read = client.post(f"/api/notifications/{first}/read", headers=headers)
    assert first_read.status_code == 200 and first_read.json()["is_read"] is True
    replay = client.post(f"/api/notifications/{first}/read", headers=headers)
    assert replay.status_code == 200
    unread = client.get("/api/notifications?only_unread=true", headers=headers)
    assert [row["id"] for row in unread.json()] == [second]
    assert client.post("/api/notifications/read-all", headers=headers).status_code == 200
    assert client.get("/api/notifications/unread-count", headers=headers).json() == {"count": 0}
    assert client.get("/api/notifications/unread-count", headers=other_headers).json() == {"count": 1}
    with SessionLocal() as db:
        assert db.get(Notification, other).is_read is False


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/notifications"), ("GET", "/api/notifications/unread-count"),
    ("POST", "/api/notifications/1/read"), ("POST", "/api/notifications/read-all"),
])
def test_notification_routes_require_login(client, method, path):
    assert client.request(method, path).status_code == 401


def test_notification_send_rejects_unrepresentable_recipient_before_lookup():
    class LookupSpy:
        called = False

        def get(self, model, user_id):
            self.called = True
            raise AssertionError("unrepresentable IDs must not reach the database")

    db = LookupSpy()
    payload = NotificationSendIn(
        target_type="user_id",
        user_id=2_147_483_648,
        title="Synthetic notice",
    )
    with pytest.raises(HTTPException) as exc_info:
        _resolve_recipients(payload, db)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Recipient user not found"
    assert db.called is False

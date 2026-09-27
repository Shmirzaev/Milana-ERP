from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.api.routes.notifications import list_my_notifications
from app.db.session import SessionLocal
from app.models import Notification
from app.schemas.tasks import NotificationOut
from app.tests.test_task_assignment_authorization import _actor


def _seed_notifications(user_id: int, count: int) -> list[int]:
    with SessionLocal() as db:
        rows = [
            Notification(user_id=user_id, title=f"Paged notice {number:04d}", is_read=False)
            for number in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return [int(row.id) for row in rows]


def _select_trace(db, callback):
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select"):
            statements.append(normalized)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        return callback(), statements
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_notification_page_is_user_scoped_bounded_and_matches_legacy_prefix(row_count):
    user_id, _ = _actor()
    other_id, _ = _actor()
    notification_ids = _seed_notifications(user_id, row_count)
    _seed_notifications(other_id, 1)
    current = SimpleNamespace(id=user_id)

    with SessionLocal() as db:
        legacy, legacy_statements = _select_trace(
            db,
            lambda: list_my_notifications(db, current, limit=500),
        )
    with SessionLocal() as db:
        page, page_statements = _select_trace(
            db,
            lambda: list_my_notifications(db, current, page=1, page_size=50),
        )

    expected_ids = list(reversed(notification_ids))[:50]
    assert [row.id for row in legacy[:50]] == expected_ids
    assert [row.id for row in page["rows"]] == expected_ids
    assert [NotificationOut.model_validate(row).model_dump() for row in page["rows"]] == [
        NotificationOut.model_validate(row).model_dump() for row in legacy[:50]
    ]
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) <= 50
    assert len(legacy_statements) == 1
    assert len(page_statements) == 1
    row_statement = next(statement for statement in page_statements if " order by notifications.id desc" in statement)
    assert "notifications.user_id = ?" in row_statement
    assert " limit ? offset ?" in row_statement
    assert "count(notifications.id) over ()" in row_statement


def test_notification_past_end_page_keeps_total_with_count_fallback():
    user_id, _ = _actor()
    _seed_notifications(user_id, 1)
    current = SimpleNamespace(id=user_id)

    with SessionLocal() as db:
        page, statements = _select_trace(
            db,
            lambda: list_my_notifications(db, current, page=4, page_size=10),
        )

    assert page == {
        "rows": [],
        "total": 1,
        "page": 4,
        "page_size": 10,
        "has_more": False,
    }
    assert len(statements) == 2
    assert "count(notifications.id) over ()" in statements[0]
    assert statements[1].startswith("select count(*)")


def test_notification_page_http_contract_preserves_legacy_filter_and_auth(client):
    user_id, headers = _actor()
    notification_ids = _seed_notifications(user_id, 2)
    with SessionLocal() as db:
        db.get(Notification, notification_ids[0]).is_read = True
        db.commit()

    legacy = client.get("/api/notifications?only_unread=true&limit=20", headers=headers)
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert [row["id"] for row in legacy.json()] == [notification_ids[1]]

    paged = client.get(
        "/api/notifications?only_unread=true&page=1&page_size=20",
        headers=headers,
    )
    assert paged.status_code == 200
    body = paged.json()
    assert body["rows"] == legacy.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["has_more"] is False

    assert client.get("/api/notifications?page_size=501", headers=headers).status_code == 422
    assert client.get("/api/notifications?page=1&page_size=20").status_code == 401

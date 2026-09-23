from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Notification, User


def test_notification_summary_combines_unread_count_and_rows(client, auth_headers):
    marker = uuid4().hex[:12]
    with SessionLocal() as db:
        user_id = int(db.query(User.id).filter(User.email == "admin@example.com").scalar())
        rows = [
            Notification(user_id=user_id, title=f"summary {marker} {index}", is_read=False)
            for index in range(5)
        ]
        rows.append(Notification(user_id=user_id, title=f"summary {marker} read", is_read=True))
        db.add_all(rows)
        db.commit()
        expected_ids = [int(row.id) for row in list(reversed(rows[:5]))[:2]]

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from notifications " in normalized:
            statements.append(normalized)

    event.listen(SessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        response = client.get("/api/notifications/summary?limit=2", headers=auth_headers)
    finally:
        event.remove(SessionLocal.kw["bind"], "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] >= 5
    assert [row["id"] for row in payload["rows"]] == expected_ids
    assert len(statements) == 1
    assert "count(notifications.id) over ()" in statements[0]

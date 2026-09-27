from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.production import list_quality
from app.db.session import SessionLocal
from app.models import AuditLog, Department, Model, ProductionOrder, QualityCheck, User, WorkOrder
from app.schemas.production import QualityCheckOut


def _seed_quality_checks(count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        department = db.query(Department).order_by(Department.id).first()
        model = db.query(Model).order_by(Model.id).first()
        user = db.query(User).order_by(User.id).first()
        assert department is not None
        assert model is not None
        assert user is not None
        order = ProductionOrder(
            production_no=f"QUALITY-PAGE-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="new",
            planned_quantity=max(count, 1),
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department.id,
            operation="cutting",
            status="waiting",
            planned_input_qty=max(count, 1),
            planned_output_qty=max(count, 1),
        )
        db.add(work_order)
        db.flush()
        started_at = datetime(2098, 1, 1, tzinfo=timezone.utc)
        rows = [
            QualityCheck(
                work_order_id=work_order.id,
                department_id=department.id,
                checked_qty=index + 1,
                passed_qty=index + 1,
                failed_qty=0,
                severity="low",
                checked_by=user.id,
                checked_at=started_at + timedelta(seconds=index),
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return int(work_order.id), [int(row.id) for row in rows]


def _read(work_order_id: int, **kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_quality(db, object(), work_order_id=work_order_id, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


def _payload(rows: list[QualityCheck]) -> list[dict]:
    return [QualityCheckOut.model_validate(row).model_dump(mode="json") for row in rows]


@pytest.mark.parametrize("count", [1, 50, 401])
def test_quality_check_pages_bound_sql_and_preserve_legacy_payload(count):
    work_order_id, created_ids = _seed_quality_checks(count)

    page, statements = _read(work_order_id, page=1, page_size=50)
    legacy, legacy_statements = _read(work_order_id, page=None, page_size=None)
    expected_count = min(count, 50)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row.id for row in page["rows"]] == list(reversed(created_ids))[:expected_count]
    assert _payload(page["rows"]) == _payload(legacy[:expected_count])
    assert len(statements) == 2, statements
    assert " limit ? offset ?" in statements[1]
    assert len(legacy_statements) == 1, legacy_statements


def test_quality_check_page_contract_authorization_filter_and_no_writes(client, auth_headers):
    work_order_id, created_ids = _seed_quality_checks(3)
    other_work_order_id, _ = _seed_quality_checks(1)
    with SessionLocal() as db:
        before = (db.query(QualityCheck).count(), db.query(AuditLog).count())

    response = client.get(
        "/api/quality/checks",
        params={"work_order_id": work_order_id, "page": 1, "page_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["has_more"] is True
    assert [row["id"] for row in payload["rows"]] == list(reversed(created_ids))[:2]
    assert all(row["work_order_id"] == work_order_id for row in payload["rows"])
    assert other_work_order_id != work_order_id
    assert client.get(
        "/api/quality/checks",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/quality/checks",
        params={"work_order_id": work_order_id, "page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with SessionLocal() as db:
        after = (db.query(QualityCheck).count(), db.query(AuditLog).count())
    assert after == before

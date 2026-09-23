from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.sewing_corrections import list_records
from app.db.session import SessionLocal
from app.models import AuditLog, Department, ProductionOrder, SewingRecord, User, WorkOrder


def _seed_records(count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        department = db.query(Department).filter(Department.code == "SEW").one()
        order = ProductionOrder(
            production_no=f"PERF35-SRH-{marker}",
            production_type="branded_stock",
            model_id=1,
            planned_quantity=max(count, 1),
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department.id,
            operation="sewing",
            status="in_progress",
            planned_input_qty=max(count, 1),
            planned_output_qty=max(count, 1),
        )
        db.add(work_order)
        db.flush()
        rows = [
            SewingRecord(
                work_order_id=work_order.id,
                input_qty=1,
                sewn_qty=1,
                passed_qty=1,
                failed_qty=0,
                rejected_qty=0,
                rework_qty=0,
                size_quantities=[],
                line_name="PERF35 line",
                notes=f"history row {index}",
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return int(work_order.id), [int(row.id) for row in rows]


def _read(work_order_id: int, **kwargs):
    with SessionLocal() as db:
        user = db.get(User, 1)
        assert user is not None
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_records(work_order_id, db, user, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_sewing_history_pages_bound_dependent_reads_and_preserve_legacy_payload(count):
    work_order_id, created_ids = _seed_records(count)
    returned_count = min(count, 50)

    page, statements = _read(work_order_id, page=1, page_size=50)
    legacy, legacy_statements = _read(work_order_id, page=None, page_size=None)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page["rows"]] == list(reversed(created_ids))[:returned_count]
    assert page["rows"] == legacy[:returned_count]
    assert len(statements) == 7, statements
    assert len(legacy_statements) == 6, legacy_statements
    assert sum("sewing_replacement_requests.production_batch_id" in sql for sql in statements) == 1
    assert sum("packaging_receipts.production_batch_id" in sql for sql in statements) == 1
    assert sum("packaging_records.production_batch_id" in sql for sql in statements) == 1


def test_sewing_history_page_contract_scope_auth_and_no_writes(client, auth_headers):
    work_order_id, created_ids = _seed_records(3)
    with SessionLocal() as db:
        before = (db.query(SewingRecord).count(), db.query(AuditLog).count())

    response = client.get(
        f"/api/work-orders/{work_order_id}/sewing-records",
        params={"page": 2, "page_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["has_more"] is False
    assert [row["id"] for row in payload["rows"]] == created_ids[:1]
    assert client.get(
        f"/api/work-orders/{work_order_id}/sewing-records",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/work-orders/2147483647/sewing-records",
        params={"page": 1, "page_size": 2},
        headers=auth_headers,
    ).status_code == 404

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        f"/api/work-orders/{work_order_id}/sewing-records",
        params={"page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with SessionLocal() as db:
        after = (db.query(SewingRecord).count(), db.query(AuditLog).count())
    assert after == before

from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.production_extra import list_assignments
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Department,
    ProductionOrder,
    SewingAssignment,
    SewingFlow,
    WorkOrder,
)
from app.schemas.sewing_assignment import SewingAssignmentOut


def _seed_assignments(count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        department = db.query(Department).filter(Department.code == "SEW").one()
        order = ProductionOrder(
            production_no=f"PERF35-ASG-{marker}",
            production_type="branded_stock",
            model_id=1,
            planned_quantity=max(count, 1),
        )
        flow = SewingFlow(
            factory_code="MIL",
            name=f"Assignment flow {marker}",
            code=f"ASG-{marker}",
            is_active=True,
        )
        db.add_all([order, flow])
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department.id,
            operation="sewing",
            status="planning",
            planned_input_qty=max(count, 1),
            planned_output_qty=max(count, 1),
        )
        db.add(work_order)
        db.flush()
        rows = [
            SewingAssignment(
                work_order_id=work_order.id,
                sewing_flow_id=flow.id,
                quantity=index + 1,
                completed_qty=0,
                status="planned",
                notes=f"PERF35 assignment {index}",
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
            payload = list_assignments(work_order_id, db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


def _payload(rows: list[SewingAssignment]) -> list[dict]:
    return [SewingAssignmentOut.model_validate(row).model_dump(mode="json") for row in rows]


def _assert_assignment_projection(statements):
    work_order_reads = [sql for sql in statements if " from work_orders " in sql]
    assignment_reads = [
        sql for sql in statements
        if " from sewing_assignments " in sql and "count(" not in sql
    ]
    assert len(work_order_reads) == 1
    assert work_order_reads[0].startswith("select work_orders.id as work_orders_id from work_orders ")
    assert len(assignment_reads) == 1
    selected_columns = assignment_reads[0].split(" from sewing_assignments ", maxsplit=1)[0]
    assert "created_at" not in selected_columns
    assert "updated_at" not in selected_columns


@pytest.mark.parametrize("count", [1, 50, 401])
def test_assignment_pages_bound_rows_and_preserve_legacy_payload(count):
    work_order_id, created_ids = _seed_assignments(count)

    page, statements = _read(work_order_id, page=1, page_size=count)
    legacy, legacy_statements = _read(work_order_id, page=None, page_size=None)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is False
    assert [row.id for row in page["rows"]] == created_ids
    assert _payload(page["rows"]) == _payload(legacy)
    assert len(statements) == 3, statements
    assert len(legacy_statements) == 2, legacy_statements
    _assert_assignment_projection(statements)
    _assert_assignment_projection(legacy_statements)
    count_queries = [statement for statement in statements if "count(" in statement]
    assert len(count_queries) == 1, statements
    assert "count(sewing_assignments.id)" in count_queries[0]
    assert "sewing_assignments.work_order_id = ?" in count_queries[0]
    assert " from (select sewing_assignments." not in count_queries[0]


def test_assignment_page_contract_not_found_auth_and_no_writes(client, auth_headers):
    work_order_id, created_ids = _seed_assignments(3)
    with SessionLocal() as db:
        before = (db.query(SewingAssignment).count(), db.query(AuditLog).count())

    response = client.get(
        f"/api/work-orders/{work_order_id}/assignments",
        params={"page": 2, "page_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["has_more"] is False
    assert [row["id"] for row in payload["rows"]] == created_ids[2:]
    assert client.get(
        f"/api/work-orders/{work_order_id}/assignments",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/work-orders/2147483647/assignments",
        params={"page": 1, "page_size": 2},
        headers=auth_headers,
    ).status_code == 404
    assert client.get(
        f"/api/work-orders/{work_order_id}/assignments",
        params={"page": 1, "page_size": 2},
    ).status_code == 401

    with SessionLocal() as db:
        after = (db.query(SewingAssignment).count(), db.query(AuditLog).count())
    assert after == before

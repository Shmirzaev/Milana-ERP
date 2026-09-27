from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes.sewing_flows import flow_work_orders
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Department,
    ProductionOrder,
    SewingAssignment,
    SewingFlow,
    WorkOrder,
)


def _factory_user(factory: str = "MIL"):
    return SimpleNamespace(
        role=SimpleNamespace(name=""),
        extra_permissions=["sewing.flows"],
        factory_code=factory,
        session_factory_code=factory,
    )


def _seed_work_orders(count: int, *, with_split: bool = False) -> tuple[int, list[int], int | None]:
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        department = db.query(Department).filter(Department.code == "SEW").one()
        flow = SewingFlow(
            factory_code="MIL",
            name=f"Paged work orders {marker}",
            code=f"PWO-{marker}",
            is_active=True,
        )
        db.add(flow)
        db.flush()

        work_orders: list[WorkOrder] = []
        for index in range(count):
            order = ProductionOrder(
                production_no=f"PERF35-FWO-{marker}-{index:04d}",
                production_type="branded_stock",
                source_type="standard",
                model_id=1,
                status="sewing",
                planned_quantity=index + 1,
            )
            db.add(order)
            db.flush()
            work_order = WorkOrder(
                production_order_id=order.id,
                department_id=department.id,
                operation="sewing",
                status="waiting",
                planned_input_qty=index + 1,
                planned_output_qty=index + 1,
                sewing_flow_id=flow.id,
            )
            db.add(work_order)
            work_orders.append(work_order)
        db.flush()

        assignment_id = None
        if with_split and work_orders:
            assignment = SewingAssignment(
                work_order_id=work_orders[0].id,
                sewing_flow_id=flow.id,
                quantity=17,
                completed_qty=4,
                status="in_progress",
            )
            db.add(assignment)
            db.flush()
            assignment_id = int(assignment.id)

        flow_id = int(flow.id)
        work_order_ids = [int(row.id) for row in work_orders]
        db.commit()
        return flow_id, work_order_ids, assignment_id


def _read(flow_id: int, **kwargs):
    with SessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = flow_work_orders(flow_id, db, _factory_user(), **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_work_order_pages_bound_rows_and_query_growth(count):
    flow_id, created_ids, _ = _seed_work_orders(count)

    page, statements = _read(
        flow_id,
        only_active=False,
        page=1,
        page_size=min(count, 25),
    )

    expected_size = min(count, 25)
    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == expected_size
    assert page["has_more"] is (count > expected_size)
    assert [row["id"] for row in page["rows"]] == list(reversed(created_ids))[:expected_size]
    assert len(statements) <= 8, statements
    assert any(" limit ? offset ?" in statement for statement in statements), statements


def test_work_order_page_preserves_legacy_mixed_row_payload_and_order():
    flow_id, created_ids, assignment_id = _seed_work_orders(55, with_split=True)

    legacy, _ = _read(flow_id, only_active=False, page=None, page_size=None)
    first, _ = _read(flow_id, only_active=False, page=1, page_size=20)
    second, _ = _read(flow_id, only_active=False, page=2, page_size=20)

    assert first["rows"] == legacy[:20]
    assert second["rows"] == legacy[20:40]
    assert first["total"] == 55
    assert first["has_more"] is True
    assert first["rows"][0]["sewing_assignment_id"] == assignment_id
    assert first["rows"][0]["id"] == created_ids[0]
    assert [row["id"] for row in legacy].count(created_ids[0]) == 1


def test_work_order_page_auth_bounds_factory_scope_and_no_writes(client, auth_headers):
    flow_id, _, _ = _seed_work_orders(3)
    with SessionLocal() as db:
        before = (
            db.query(WorkOrder).count(),
            db.query(SewingAssignment).count(),
            db.query(AuditLog).count(),
        )

    response = client.get(
        f"/api/sewing-flows/{flow_id}/work-orders",
        params={"page": 2, "page_size": 2},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 3
    assert response.json()["page"] == 2
    assert len(response.json()["rows"]) == 1
    assert client.get(
        f"/api/sewing-flows/{flow_id}/work-orders",
        params={"page": 1, "page_size": 2},
    ).status_code == 401
    assert client.get(
        f"/api/sewing-flows/{flow_id}/work-orders",
        params={"page": 0, "page_size": 2},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        f"/api/sewing-flows/{flow_id}/work-orders",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/sewing-flows/2147483647/work-orders",
        params={"page": 1, "page_size": 2},
        headers=auth_headers,
    ).status_code == 404

    with SessionLocal() as db:
        with pytest.raises(HTTPException) as denied:
            flow_work_orders(
                flow_id,
                db,
                _factory_user("ECO"),
                only_active=False,
                page=1,
                page_size=2,
            )
        assert denied.value.status_code == 403

    with SessionLocal() as db:
        after = (
            db.query(WorkOrder).count(),
            db.query(SewingAssignment).count(),
            db.query(AuditLog).count(),
        )
    assert after == before

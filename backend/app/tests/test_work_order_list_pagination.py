from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.production import list_wos
from app.db.session import SessionLocal
from app.models import Department, Model, ProductionOrder, WorkOrder


def _factory_user():
    return SimpleNamespace(
        role=SimpleNamespace(name="", permissions=[]),
        extra_permissions=["production.view"],
        access_policy={},
        factory_code="MIL",
        session_factory_code="MIL",
    )


def _seed_work_orders(count, *, operation, status="waiting"):
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        department_id = db.query(Department.id).filter(Department.code == "CUT").scalar()
        assert department_id is not None
        models = [
            Model(
                code=f"PERF35-WO-M-{marker}-{number:04d}",
                name=f"Bounded work-order model {number}",
                status="approved",
            )
            for number in range(count)
        ]
        db.add_all(models)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF35-WO-PO-{marker}-{number:04d}",
                production_type="branded_stock",
                model_id=model.id,
                planned_quantity=1,
            )
            for number, model in enumerate(models)
        ]
        db.add_all(orders)
        db.flush()
        work_orders = [
            WorkOrder(
                production_order_id=order.id,
                department_id=department_id,
                operation=operation,
                status=status,
                planned_input_qty=1,
                planned_output_qty=1,
            )
            for order in orders
        ]
        db.add_all(work_orders)
        db.commit()
        return [int(row.id) for row in work_orders]


def _read(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_wos(db, _factory_user(), **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_work_order_pages_bound_rows_and_dependent_queries(count):
    operation = f"perf35_{uuid4().hex[:12]}"
    created_ids = _seed_work_orders(count, operation=operation)
    returned_count = min(count, 50)

    page, statements = _read(operation=operation, page=1, page_size=50)
    legacy, _ = _read(operation=operation)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page["rows"]] == list(reversed(created_ids))[:returned_count]
    assert page["rows"] == legacy[:returned_count]
    assert all(row["operation"] == operation for row in page["rows"])
    assert len(statements) == 5, "\n\n".join(statements)
    dependent_queries = statements[2:]
    assert all(" in (" in statement for statement in dependent_queries), statements
    assert all(statement.count("?") == returned_count for statement in dependent_queries), statements


def test_work_order_page_applies_status_before_count(client, auth_headers):
    operation = f"perf35_{uuid4().hex[:12]}"
    created_ids = _seed_work_orders(1, operation=operation, status="paused")

    response = client.get(
        "/api/work-orders",
        params={"operation": operation, "status": "paused", "page": 1, "page_size": 1},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert [row["id"] for row in page["rows"]] == created_ids
    assert page["rows"][0]["status"] == "paused"


def test_work_order_page_size_is_bounded(client, auth_headers):
    response = client.get(
        "/api/work-orders",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text

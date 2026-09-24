from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes import inbox
from app.models import Department, Model, ProductionBatch, ProductionOrder, WorkOrder
from app.tests.conftest import TestSessionLocal, test_engine


def _create_packaging_batches(db, count: int, *, prefix: str):
    model = Model(code=f"PKG-{prefix}", name="Awaiting packaging pagination")
    db.add(model)
    db.flush()
    production_order = ProductionOrder(
        production_no=f"PKG-{prefix}",
        production_type="client_order",
        model_id=model.id,
        status="in_progress",
        planned_quantity=max(1, count * 100),
    )
    db.add(production_order)
    db.flush()
    sewing_department = db.query(Department).filter(Department.code == "SEW").first()
    packaging_department = db.query(Department).filter(Department.code == "PKG").first()
    assert sewing_department is not None
    assert packaging_department is not None

    batches = [
        ProductionBatch(
            production_order_id=production_order.id,
            batch_no=f"B{index + 1:03}",
            batch_index=index + 1,
            planned_quantity=100,
        )
        for index in range(count)
    ]
    db.add_all(batches)
    db.flush()
    work_orders = []
    for batch in batches:
        work_orders.extend((
            WorkOrder(
                production_order_id=production_order.id,
                production_batch_id=batch.id,
                department_id=sewing_department.id,
                operation="sewing",
                status="completed",
                passed_qty=100,
            ),
            WorkOrder(
                production_order_id=production_order.id,
                production_batch_id=batch.id,
                department_id=packaging_department.id,
                operation="packaging",
                status="in_progress",
                passed_qty=20,
            ),
        ))
    db.add_all(work_orders)
    db.flush()
    return production_order, batches, sewing_department, packaging_department


@pytest.mark.parametrize("batch_count", [1, 50, 401])
def test_awaiting_packaging_page_has_exact_totals_and_constant_query_count(batch_count):
    prefix = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        _production_order, batches, _sewing_department, packaging_department = _create_packaging_batches(
            db, batch_count, prefix=prefix,
        )
        db.commit()
        packaging_department_id = int(packaging_department.id)
        statements = []

        def count_statement(*_args):
            statements.append(1)

        event.listen(test_engine, "before_cursor_execute", count_statement)
        try:
            with TestSessionLocal() as page_db:
                first_rows, total = inbox._awaiting_packaging_rows(
                    page_db, packaging_department_id, offset=0, limit=50,
                )
            first_query_count = len(statements)
            with TestSessionLocal() as page_db:
                last_rows, last_total = inbox._awaiting_packaging_rows(
                    page_db, packaging_department_id, offset=batch_count - 1, limit=50,
                )
            last_query_count = len(statements) - first_query_count
        finally:
            event.remove(test_engine, "before_cursor_execute", count_statement)

    assert total == batch_count
    assert last_total == batch_count
    assert len(first_rows) == min(batch_count, 50)
    assert len(last_rows) == 1
    assert first_rows[0]["batch_no"] == "B001"
    assert last_rows[0]["production_batch_id"] == batches[-1].id
    assert {row["ready_qty"] for row in first_rows + last_rows} == {80}
    assert first_query_count <= 12
    assert last_query_count <= 12
    assert abs(first_query_count - last_query_count) <= 1


def test_awaiting_packaging_pairs_each_batch_and_null_batch_exactly_and_matches_legacy_summary(
    client,
    auth_headers,
):
    prefix = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        production_order, batches, sewing_department, packaging_department = _create_packaging_batches(
            db, 3, prefix=prefix,
        )
        # The third batch is complete; only the first two batch pairs remain open.
        third_sewing = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == production_order.id,
            WorkOrder.production_batch_id == batches[2].id,
            WorkOrder.operation == "sewing",
        ).one()
        third_packaging = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == production_order.id,
            WorkOrder.production_batch_id == batches[2].id,
            WorkOrder.operation == "packaging",
        ).one()
        third_sewing.passed_qty = 50
        third_packaging.passed_qty = 50
        db.add_all((
            WorkOrder(
                production_order_id=production_order.id,
                production_batch_id=None,
                department_id=sewing_department.id,
                operation="sewing",
                status="completed",
                passed_qty=9,
            ),
            WorkOrder(
                production_order_id=production_order.id,
                production_batch_id=None,
                department_id=sewing_department.id,
                operation="sewing",
                status="completed",
                passed_qty=11,
            ),
            WorkOrder(
                production_order_id=production_order.id,
                production_batch_id=None,
                department_id=packaging_department.id,
                operation="packaging",
                status="in_progress",
                passed_qty=2,
            ),
            WorkOrder(
                production_order_id=production_order.id,
                production_batch_id=None,
                department_id=packaging_department.id,
                operation="packaging",
                status="in_progress",
                passed_qty=3,
            ),
        ))
        db.commit()
        po_id = int(production_order.id)
        expected = {
            None: (20, 5, 15),
            int(batches[0].id): (100, 20, 80),
            int(batches[1].id): (100, 20, 80),
        }

    page_one = client.get(
        "/api/inbox/awaiting-packaging?dept=PKG&page=1&page_size=2",
        headers=auth_headers,
    )
    page_two = client.get(
        "/api/inbox/awaiting-packaging?dept=PKG&page=2&page_size=2",
        headers=auth_headers,
    )
    legacy = client.get("/api/inbox?dept=PKG", headers=auth_headers)
    assert page_one.status_code == 200, page_one.text
    assert page_two.status_code == 200, page_two.text
    assert legacy.status_code == 200, legacy.text
    paged_rows = page_one.json()["rows"] + page_two.json()["rows"]
    assert page_one.json()["total"] == page_two.json()["total"] == 3
    assert page_one.json()["has_more"] is True
    assert page_two.json()["has_more"] is False
    assert len({(row["production_order_id"], row["production_batch_id"]) for row in paged_rows}) == 3
    assert all(row["production_order_id"] == po_id for row in paged_rows)
    assert {
        row["production_batch_id"]: (row["sewn_passed"], row["already_packed"], row["ready_qty"])
        for row in paged_rows
    } == expected
    assert {row["production_batch_id"]: row["batch_no"] for row in paged_rows} == {
        None: None,
        int(batches[0].id): "B001",
        int(batches[1].id): "B002",
    }
    legacy_rows = [row for row in legacy.json()["awaiting_packaging"] if row["production_order_id"] == po_id]
    assert {
        row["production_batch_id"]: (row["sewn_passed"], row["already_packed"], row["ready_qty"])
        for row in legacy_rows
    } == expected
    paged_references = {
        row["production_batch_id"]: (row["production_no"], row["order_no"], row["sales_order_no"])
        for row in paged_rows
    }
    legacy_references = {
        row["production_batch_id"]: (row["production_no"], row["order_no"], row["sales_order_no"])
        for row in legacy_rows
    }
    assert paged_references == legacy_references


def test_awaiting_packaging_page_requires_auth_and_bounds_page_size(client, auth_headers):
    assert client.get("/api/inbox/awaiting-packaging?dept=PKG").status_code == 401
    assert client.get(
        "/api/inbox/awaiting-packaging?dept=PKG&page_size=101",
        headers=auth_headers,
    ).status_code == 422
    wrong_department = client.get(
        "/api/inbox/awaiting-packaging?dept=SEW",
        headers=auth_headers,
    )
    assert wrong_department.status_code == 404

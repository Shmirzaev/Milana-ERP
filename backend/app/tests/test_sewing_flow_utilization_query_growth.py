from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes import sewing_flows
from app.db.session import SessionLocal
from app.models import (
    Department,
    Model,
    ProductionOrder,
    SewingAssignment,
    SewingFlow,
    WorkOrder,
)


def _select_count(db, call):
    count = 0

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal count
        if statement.lstrip().upper().startswith("SELECT"):
            count += 1

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, count


def _factory_user(factory="MIL"):
    return SimpleNamespace(
        role=SimpleNamespace(name=""), extra_permissions=["sewing.flows"],
        factory_code=factory, session_factory_code=factory,
    )


def _flow_set(db, count):
    suffix = uuid4().hex[:8]
    department = db.query(Department).filter_by(code="MIL").one()
    models = [
        Model(code=f"PERF16-M-{suffix}-{number:04d}", name="Utilization model", status="approved")
        for number in range(count)
    ]
    flows = [
        SewingFlow(
            factory_code="MIL", code=f"PERF16-{suffix}-{number:04d}",
            name=f"Utilization {suffix} {number}", capacity_per_day=10, is_active=True,
        )
        for number in range(count)
    ]
    db.add_all([*models, *flows])
    db.flush()
    orders = [
        ProductionOrder(
            production_no=f"PERF16-PO-{suffix}-{number:04d}", production_type="branded_stock",
            model_id=models[number].id, planned_quantity=10,
        )
        for number in range(count)
    ]
    db.add_all(orders)
    db.flush()
    db.add_all([
        WorkOrder(
            production_order_id=orders[number].id, department_id=department.id,
            operation="sewing", status="waiting", sewing_flow_id=flows[number].id,
            planned_output_qty=10, passed_qty=2,
        )
        for number in range(count)
    ])
    db.commit()
    return [flow.id for flow in flows]


def _active_flow_set(db, count, *, factory="MIL"):
    suffix = uuid4().hex[:8].upper()
    rows = [
        SewingFlow(
            factory_code=factory,
            code=f"PERF35-UTIL-{suffix}-{number:04d}",
            name=f"Paged utilization {suffix} {number}",
            capacity_per_day=number + 1,
            is_active=True,
        )
        for number in range(count)
    ]
    db.add_all(rows)
    db.commit()
    return [int(row.id) for row in rows]


def _read_utilization(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = sewing_flows.utilization_snapshot(db, _factory_user(), **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize(("flow_count", "expected_selects"), [(1, 3), (50, 3), (401, 5)])
def test_utilization_snapshot_queries_are_chunk_bounded(flow_count, expected_selects):
    with SessionLocal() as db:
        flow_ids = _flow_set(db, flow_count)
    with SessionLocal() as db:
        payload, select_count = _select_count(
            db, lambda: sewing_flows.utilization_snapshot(db, _factory_user()),
        )

    assert select_count == expected_selects
    by_id = {row["flow_id"]: row for row in payload}
    assert [by_id[flow_id]["committed_today"] for flow_id in flow_ids] == [8] * flow_count


@pytest.mark.parametrize("flow_count", [1, 50, 401])
def test_utilization_snapshot_page_bounds_rows_and_preserves_legacy_payload(flow_count):
    with SessionLocal() as db:
        baseline = db.query(SewingFlow).filter(
            SewingFlow.factory_code == "MIL",
            SewingFlow.is_active.is_(True),
        ).count()
        _active_flow_set(db, flow_count)

    page, statements = _read_utilization(page=1, page_size=50)
    legacy, _ = _read_utilization()

    selects = [statement for statement in statements if statement.startswith("select")]
    writes = [
        statement for statement in statements
        if statement.startswith(("insert", "update", "delete"))
    ]
    assert page["total"] == baseline + flow_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (page["total"] > 50)
    assert page["rows"] == legacy[:50]
    assert len(page["rows"]) == min(page["total"], 50)
    assert len(selects) == 4, selects
    assert all(" in (" in statement for statement in selects[2:]), selects
    assert writes == []


def _work_order(db, *, model_id, department_id, suffix, number, flow_id=None,
                status="waiting", planned=0, passed=0):
    order = ProductionOrder(
        production_no=f"PERF16-SEM-PO-{suffix}-{number}", production_type="branded_stock",
        model_id=model_id, planned_quantity=max(0, planned),
    )
    db.add(order)
    db.flush()
    work_order = WorkOrder(
        production_order_id=order.id, department_id=department_id,
        operation="sewing", status=status, sewing_flow_id=flow_id,
        planned_output_qty=max(0, planned), passed_qty=max(0, passed),
    )
    db.add(work_order)
    db.flush()
    return work_order


def test_batched_utilization_matches_scalar_status_time_and_rounding_semantics():
    suffix = uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        department = db.query(Department).filter_by(code="MIL").one()
        model = Model(code=f"PERF16-SEM-M-{suffix}", name="Semantic model", status="approved")
        flows = [
            SewingFlow(factory_code="MIL", code=f"PERF16-A-{suffix}", name=f"A {suffix}", capacity_per_day=100),
            SewingFlow(factory_code="MIL", code=f"PERF16-B-{suffix}", name=f"B {suffix}", capacity_per_day=1),
            SewingFlow(factory_code="MIL", code=f"PERF16-C-{suffix}", name=f"C {suffix}", capacity_per_day=0),
            SewingFlow(factory_code="MIL", code=f"PERF16-D-{suffix}", name=f"D {suffix}", capacity_per_day=-5),
            SewingFlow(
                factory_code="MIL", code=f"PERF16-Z-{suffix}", name=f"Inactive {suffix}",
                capacity_per_day=1, is_active=False,
            ),
            SewingFlow(factory_code="BST", code=f"PERF16-X-{suffix}", name=f"Other {suffix}", capacity_per_day=1),
        ]
        db.add_all([model, *flows])
        db.flush()

        direct = _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=1,
            flow_id=flows[0].id, planned=100, passed=20,
        )
        db.add(SewingAssignment(
            work_order_id=direct.id, sewing_flow_id=flows[0].id,
            quantity=100, completed_qty=0, status="cancelled",
        ))

        split = _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=2,
            planned=10,
        )
        db.add(SewingAssignment(
            work_order_id=split.id, sewing_flow_id=flows[1].id,
            quantity=10, completed_qty=0,
            planned_start=now - timedelta(days=2), planned_end=now + timedelta(days=2),
            status="planned",
        ))
        missing_dates = _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=3,
            planned=10,
        )
        future = _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=4,
            planned=10,
        )
        completed_wo = _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=5,
            status="completed", planned=10,
        )
        expired = _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=10,
            planned=10,
        )
        overcompleted = _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=11,
            planned=10,
        )
        db.add_all([
            SewingAssignment(
                work_order_id=missing_dates.id, sewing_flow_id=flows[1].id,
                quantity=10, completed_qty=0, status="in_progress",
            ),
            SewingAssignment(
                work_order_id=future.id, sewing_flow_id=flows[1].id,
                quantity=10, completed_qty=0,
                planned_start=now + timedelta(days=1), planned_end=now + timedelta(days=2),
                status="planned",
            ),
            SewingAssignment(
                work_order_id=completed_wo.id, sewing_flow_id=flows[1].id,
                quantity=10, completed_qty=0,
                planned_start=now - timedelta(days=1), planned_end=now + timedelta(days=1),
                status="planned",
            ),
            SewingAssignment(
                work_order_id=expired.id, sewing_flow_id=flows[1].id,
                quantity=10, completed_qty=0,
                planned_start=now - timedelta(days=3), planned_end=now - timedelta(days=2),
                status="planned",
            ),
            SewingAssignment(
                work_order_id=overcompleted.id, sewing_flow_id=flows[1].id,
                quantity=5, completed_qty=10,
                planned_start=now - timedelta(days=1), planned_end=now + timedelta(days=1),
                status="in_progress",
            ),
        ])

        managed_direct = _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=6,
            flow_id=flows[2].id, planned=50,
        )
        db.add(SewingAssignment(
            work_order_id=managed_direct.id, sewing_flow_id=flows[2].id,
            quantity=50, completed_qty=50, status="completed",
        ))
        _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=12,
            flow_id=flows[2].id, planned=5, passed=10,
        )
        _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=7,
            flow_id=flows[3].id, status="paused", planned=5,
        )
        _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=8,
            flow_id=flows[4].id, planned=1,
        )
        _work_order(
            db, model_id=model.id, department_id=department.id, suffix=suffix, number=9,
            flow_id=flows[5].id, planned=1,
        )
        db.commit()
        flow_ids = [flow.id for flow in flows]

        scalar = {flow_id: sewing_flows._committed_today(db, flow_id) for flow_id in flow_ids}
        batched = sewing_flows._committed_today_by_flow(db, flow_ids, now=now)
        assert batched == scalar == {
            flows[0].id: 80, flows[1].id: 2, flows[2].id: 0,
            flows[3].id: 5, flows[4].id: 1, flows[5].id: 1,
        }
        assert sewing_flows._committed_today_by_flow(db, []) == {}

        payload = sewing_flows.utilization_snapshot(db, _factory_user())

    selected = [row for row in payload if row["flow_id"] in set(flow_ids)]
    assert [row["flow_id"] for row in selected] == [flow.id for flow in flows[:4]]
    assert [row["committed_today"] for row in selected] == [80, 2, 0, 5]
    assert [row["utilization_pct"] for row in selected] == [80.0, 200.0, 0, -100.0]
    assert [row["is_full"] for row in selected] == [False, True, False, False]


def test_utilization_snapshot_requires_authentication(client):
    response = client.get(
        "/api/sewing-flows/utilization-snapshot",
        params={"page": 1, "page_size": 50},
    )
    assert response.status_code == 401


def test_utilization_snapshot_page_preserves_factory_scope(client, auth_headers):
    response = client.get(
        "/api/sewing-flows/utilization-snapshot",
        params={"factory_code": "BST", "page": 1, "page_size": 50},
        headers=auth_headers,
    )

    assert response.status_code == 403, response.text


def test_utilization_snapshot_page_size_is_bounded(client, auth_headers):
    response = client.get(
        "/api/sewing-flows/utilization-snapshot",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text

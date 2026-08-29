from uuid import uuid4

from app.db.session import SessionLocal
from app.models import Department, ProductionOrder, SewingAssignment, SewingFlow, WorkOrder


def test_active_sewing_assignment_moves_between_lines_in_same_factory(client, auth_headers):
    suffix = uuid4().hex[:8].upper()
    db = SessionLocal()
    try:
        sewing_department = db.query(Department).filter(Department.code == "SEW").one()
        production_order = ProductionOrder(
            production_no=f"PO-MOVE-{suffix}",
            production_type="branded_stock",
            model_id=1,
            planned_quantity=100,
        )
        source_flow = SewingFlow(
            factory_code="MIL",
            name=f"Move Source {suffix}",
            code=f"MOVE-SRC-{suffix}",
            capacity_per_day=100,
            is_active=True,
        )
        destination_flow = SewingFlow(
            factory_code="MIL",
            name=f"Move Destination {suffix}",
            code=f"MOVE-DST-{suffix}",
            capacity_per_day=100,
            is_active=True,
        )
        other_factory_flow = SewingFlow(
            factory_code="ECO",
            name=f"Move Other Factory {suffix}",
            code=f"MOVE-ECO-{suffix}",
            capacity_per_day=100,
            is_active=True,
        )
        db.add_all([production_order, source_flow, destination_flow, other_factory_flow])
        db.flush()
        work_order = WorkOrder(
            production_order_id=production_order.id,
            department_id=sewing_department.id,
            operation="sewing",
            status="in_progress",
            planned_input_qty=100,
            planned_output_qty=100,
            sewing_flow_id=source_flow.id,
        )
        db.add(work_order)
        db.flush()
        assignment = SewingAssignment(
            work_order_id=work_order.id,
            sewing_flow_id=source_flow.id,
            quantity=100,
            completed_qty=25,
            status="in_progress",
        )
        db.add(assignment)
        db.commit()
        assignment_id = int(assignment.id)
        work_order_id = int(work_order.id)
        source_flow_id = int(source_flow.id)
        destination_flow_id = int(destination_flow.id)
        other_factory_flow_id = int(other_factory_flow.id)
    finally:
        db.close()

    cross_factory = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        json={"sewing_flow_id": other_factory_flow_id},
        headers=auth_headers,
    )
    assert cross_factory.status_code == 403, cross_factory.text
    assert "Eco Cotton" in cross_factory.text

    moved = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        json={"sewing_flow_id": destination_flow_id},
        headers=auth_headers,
    )
    assert moved.status_code == 200, moved.text
    assert int(moved.json()["sewing_flow_id"]) == destination_flow_id
    assert int(moved.json()["completed_qty"]) == 25
    assert moved.json()["status"] == "in_progress"

    source_rows = client.get(
        f"/api/sewing-flows/{source_flow_id}/work-orders?only_active=true",
        headers=auth_headers,
    )
    destination_rows = client.get(
        f"/api/sewing-flows/{destination_flow_id}/work-orders?only_active=true",
        headers=auth_headers,
    )
    assert source_rows.status_code == 200, source_rows.text
    assert destination_rows.status_code == 200, destination_rows.text
    assert assignment_id not in {int(row.get("sewing_assignment_id") or 0) for row in source_rows.json()}
    moved_row = next(
        row for row in destination_rows.json()
        if int(row.get("sewing_assignment_id") or 0) == assignment_id
    )
    assert int(moved_row["id"]) == work_order_id
    assert int(moved_row["passed_qty"]) == 25

    db = SessionLocal()
    try:
        refreshed_work_order = db.get(WorkOrder, work_order_id)
        assert refreshed_work_order is not None
        assert int(refreshed_work_order.sewing_flow_id or 0) == destination_flow_id
    finally:
        db.close()

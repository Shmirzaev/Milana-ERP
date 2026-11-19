import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.schemas import Department, ProductionOrder, WorkOrder
from app.models.production.order_routing_read_service import production_order_list_output
from app.libs.dto.production.production import ProductionOrderListOut
from app.tests.eco_fabric_fixture import make_eco_fabric_case, planning_payload


@pytest.mark.parametrize("include_total", [False, True])
def test_production_list_keeps_actual_ect_route_for_passport_order_selector(client, include_total):
    case = make_eco_fabric_case(SessionLocal)
    created = client.post("/api/planning/create-branded-production", headers=case["mil_headers"], json=planning_payload(case))
    assert created.status_code == 201, created.text
    order = created.json()
    response = client.get("/api/production-orders", headers=case["eco_headers"], params={"include_total": include_total, "page_size": 500})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"] if include_total else response.json()
    assert next(row for row in rows if row["id"] == order["id"])["cutting_department_code"] == "ECT"


def test_ambiguous_or_cancelled_cutting_is_not_guessed_as_ect(client):
    case = make_eco_fabric_case(SessionLocal)
    created = client.post("/api/planning/create-branded-production", headers=case["mil_headers"], json=planning_payload(case))
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    with SessionLocal() as db:
        mil = db.query(Department).filter_by(code="CUT").one()
        other = WorkOrder(production_order_id=order_id, department_id=mil.id, operation="cutting", status="waiting")
        db.add(other); db.commit(); other_id = other.id
    def route():
        response = client.get("/api/production-orders", headers=case["eco_headers"], params={"page_size": 500})
        assert response.status_code == 200, response.text
        return next(row for row in response.json() if row["id"] == order_id)["cutting_department_code"]
    assert route() is None
    with SessionLocal() as db:
        db.get(WorkOrder, other_id).status = "cancelled"
        db.commit()
    assert route() == "ECT"
    with SessionLocal() as db:
        for row in db.query(WorkOrder).filter_by(production_order_id=order_id, operation="cutting"):
            row.status = "cancelled"
        db.commit()
    assert route() is None


def test_routing_projection_is_one_batched_query_for_all_returned_orders(client):
    case = make_eco_fabric_case(SessionLocal)
    for _ in range(2):
        response = client.post("/api/planning/create-branded-production", headers=case["mil_headers"], json=planning_payload(case))
        assert response.status_code == 201, response.text
    with SessionLocal() as db:
        rows = db.query(ProductionOrder).all()
        statements = []
        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if "FROM work_orders" in statement:
                statements.append(statement)
        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = production_order_list_output(db, rows)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(result) == len(rows)
        assert all(isinstance(row, ProductionOrderListOut) for row in result)
        assert [row.id for row in result] == [row.id for row in rows]
        assert len(statements) == 1

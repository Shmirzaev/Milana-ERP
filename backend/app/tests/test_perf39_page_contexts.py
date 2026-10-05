from contextlib import contextmanager

from sqlalchemy import event

from app.db.session import engine
from app.db.session import SessionLocal
from app.models import Model


@contextmanager
def _query_counter():
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _create_sales_and_production_order(client, headers) -> tuple[int, int]:
    sales = client.post(
        "/api/sales-orders",
        json={
            "order_type": "client_order",
            "notes": "PERF39 context",
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "quantity": 12, "unit_price": 10},
            ],
        },
        headers=headers,
    )
    assert sales.status_code == 201, sales.text
    sales_order_id = int(sales.json()["id"])
    confirmed = client.post(f"/api/sales-orders/{sales_order_id}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text

    production = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": sales_order_id,
            "model_id": 1,
            "planned_quantity": 12,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 12},
            ],
        },
        headers=headers,
    )
    assert production.status_code == 201, production.text
    return sales_order_id, int(production.json()["id"])


def test_production_page_context_replaces_model_waterfall_with_minimal_projection(client, auth_headers):
    _sales_order_id, production_order_id = _create_sales_and_production_order(client, auth_headers)

    with SessionLocal() as db:
        model = db.get(Model, 1)
        fabric_row = next(
            row
            for row in model.bom
            if row.item and str(row.item.category or "").lower() in {"fabric", "semi_finished"}
        )
        fabric_row.item.composition_json = [{"name": "Cotton", "percentage": 100}]
        db.commit()

    with _query_counter() as old_queries:
        old_production = client.get(f"/api/production-orders/{production_order_id}", headers=auth_headers)
        old_model = client.get("/api/models/1", headers=auth_headers)
    assert old_production.status_code == 200, old_production.text
    assert old_model.status_code == 200, old_model.text

    with _query_counter() as context_queries:
        response = client.get(
            f"/api/production-orders/{production_order_id}/page-context",
            headers=auth_headers,
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["production_order"]["id"] == production_order_id
    assert body["model"]["id"] == 1
    assert set(body["model"]) == {
        "id", "code", "name", "details_json", "material_composition", "images", "bom",
    }
    assert body["model"]["material_composition"] == old_model.json()["material_composition"]
    assert body["model"]["images"] == []
    assert body["model"]["bom"] == []
    assert len(context_queries) < len(old_queries)

    assert client.get(f"/api/production-orders/{production_order_id}/page-context").status_code == 401
    assert client.get("/api/production-orders/2147483647/page-context", headers=auth_headers).status_code == 404






def test_production_context_respects_factory_grants_and_routed_orders(client, auth_headers):
    from uuid import uuid4
    from app.core.security import create_access_token
    from app.models import Department, ProductionOrder, Role, User, WorkOrder

    marker = uuid4().hex
    with SessionLocal() as db:
        role = Role(name=f"Context scope {marker}", permissions=["planning.production"])
        db.add(role)
        db.flush()
        user = User(name="Scoped planner", email=f"context-{marker}@test.invalid", password_hash="unused",
                    role_id=role.id, factory_code="MIL", is_active=True)
        db.add(user)
        eco = db.query(Department).filter(Department.code == "ECO").one()
        cutting = db.query(Department).filter(Department.code == "CUT").one()
        po = ProductionOrder(production_no=f"CTX-SCOPE-{marker}", model_id=1,
                             production_type="branded_stock", planned_quantity=10, status="new")
        db.add(po)
        db.flush()
        db.add(WorkOrder(production_order_id=po.id, department_id=eco.id, operation="sewing",
                         planned_input_qty=10, planned_output_qty=10, status="waiting"))
        db.commit()
        pid, uid, cut_id = po.id, user.id, cutting.id
    headers = {"Authorization": f"Bearer {create_access_token(uid, extra={'factory_code': 'MIL'})}"}
    url = f"/api/production-orders/{pid}/page-context"
    assert client.get(url, headers=headers).status_code == 403
    assert client.get(url, headers=auth_headers).status_code == 200
    with SessionLocal() as db:
        db.get(User, uid).extra_permissions = ["factory:ECO:planning.production"]
        db.commit()
    assert client.get(url, headers=headers).status_code == 200
    with SessionLocal() as db:
        db.get(User, uid).extra_permissions = []
        db.add(WorkOrder(production_order_id=pid, department_id=cut_id, operation="cutting",
                         planned_input_qty=10, planned_output_qty=10, status="waiting"))
        db.commit()
    assert client.get(url, headers=headers).status_code == 200

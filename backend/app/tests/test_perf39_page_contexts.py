from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import event

from app.db.session import engine
from app.db.session import SessionLocal
from app.core.security import create_access_token
from app.models import Model, ProductionOrder, Role, User, WorkOrder


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


def test_sales_order_page_context_combines_only_authorized_requirements(client, auth_headers):
    sales_order_id, _production_order_id = _create_sales_and_production_order(client, auth_headers)

    with _query_counter() as old_queries:
        old_order = client.get(f"/api/sales-orders/{sales_order_id}", headers=auth_headers)
        old_requirements = client.get(
            f"/api/planning/material-requirements/{sales_order_id}",
            headers=auth_headers,
        )
    assert old_order.status_code == 200, old_order.text
    assert old_requirements.status_code == 200, old_requirements.text

    with _query_counter() as context_queries:
        response = client.get(f"/api/sales-orders/{sales_order_id}/page-context", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sales_order"]["id"] == sales_order_id
    assert body["material_requirements"] == old_requirements.json()
    assert len(context_queries) < len(old_queries)

    with SessionLocal() as db:
        role = Role(name=f"PERF39 no requirements {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="PERF39 authenticated reader",
            email=f"perf39-{uuid4().hex}@example.com",
            password_hash="unused-perf39-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(user)
        db.commit()
        reader_headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    reader = client.get(f"/api/sales-orders/{sales_order_id}/page-context", headers=reader_headers)
    assert reader.status_code == 200, reader.text
    assert reader.json()["sales_order"]["id"] == sales_order_id
    assert reader.json()["material_requirements"] is None
    assert client.get("/api/sales-orders/2147483647/page-context", headers=reader_headers).status_code == 404


def test_work_order_page_context_replaces_three_stage_chain_and_preserves_model_scope(client, auth_headers):
    sales_order_id, production_order_id = _create_sales_and_production_order(client, auth_headers)
    work_orders = client.get(
        "/api/work-orders",
        params={"production_order_id": production_order_id},
        headers=auth_headers,
    )
    assert work_orders.status_code == 200, work_orders.text
    cutting = next(row for row in work_orders.json() if row["operation"] == "cutting")
    work_order_id = int(cutting["id"])

    with _query_counter() as old_queries:
        old_work_order = client.get(f"/api/work-orders/{work_order_id}", headers=auth_headers)
        old_production = client.get(f"/api/production-orders/{production_order_id}", headers=auth_headers)
        old_sales = client.get(f"/api/sales-orders/{sales_order_id}", headers=auth_headers)
        old_model = client.get("/api/models/1", headers=auth_headers)
    for response in (old_work_order, old_production, old_sales, old_model):
        assert response.status_code == 200, response.text

    with _query_counter() as context_queries:
        response = client.get(f"/api/work-orders/{work_order_id}/page-context", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["work_order"]["id"] == work_order_id
    assert body["production_order"]["id"] == production_order_id
    assert body["sales_order"]["id"] == sales_order_id
    assert body["model"]["id"] == 1
    assert isinstance(body["model"]["bom"], list)
    assert len(context_queries) < len(old_queries)

    with SessionLocal() as db:
        role = Role(name=f"PERF39 no production {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="PERF39 denied production reader",
            email=f"perf39-denied-{uuid4().hex}@example.com",
            password_hash="unused-perf39-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    assert client.get(f"/api/work-orders/{work_order_id}/page-context", headers=denied_headers).status_code == 403
    assert client.get("/api/work-orders/2147483647/page-context", headers=auth_headers).status_code == 404

    # Match the old endpoint split exactly: only cutting used the usluga model
    # route, while all other operation pages used the standard catalogue.
    with SessionLocal() as db:
        db.get(ProductionOrder, production_order_id).source_type = "usluga"
        db.get(Model, 1).catalog_scope = "usluga"
        db.commit()
    with _query_counter() as factory_denied_queries:
        factory_denied = client.get(
            f"/api/production-orders/{production_order_id}/page-context",
            headers=auth_headers,
        )
    assert factory_denied.status_code == 403, factory_denied.text
    factory_denied_sql = "\n".join(factory_denied_queries).lower()
    for child_table in ("production_order_items", "production_order_batches", "work_orders", "models"):
        assert child_table not in factory_denied_sql
    eco_headers = {"Authorization": f"Bearer {create_access_token(1, {'factory_code': 'ECO'})}"}
    usluga_cutting = client.get(f"/api/work-orders/{work_order_id}/page-context", headers=eco_headers)
    assert usluga_cutting.status_code == 200, usluga_cutting.text
    assert usluga_cutting.json()["model"]["id"] == 1
    production_context = client.get(
        f"/api/production-orders/{production_order_id}/page-context",
        headers=eco_headers,
    )
    assert production_context.status_code == 200, production_context.text
    assert production_context.json()["model"] is None

    with SessionLocal() as db:
        db.get(WorkOrder, work_order_id).operation = "packaging"
        db.commit()
    usluga_packaging = client.get(f"/api/work-orders/{work_order_id}/page-context", headers=eco_headers)
    assert usluga_packaging.status_code == 200, usluga_packaging.text
    assert usluga_packaging.json()["model"] is None

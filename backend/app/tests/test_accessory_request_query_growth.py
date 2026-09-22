from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models import (
    Department,
    Item,
    ManualAccessoryIssue,
    MaterialReservation,
    Model,
    ModelBOM,
    ProductionOrder,
    ProductionOrderItem,
    SalesOrder,
    StockBatch,
    StockMovement,
    Warehouse,
    WorkOrder,
)
from app.services.inventory import accessory_issue_plan, accessory_issue_requests
from app.services import inventory as inventory_service
from app.tests.conftest import TestSessionLocal, test_engine


def _accessory_request_orders(count: int) -> int:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF02-{marker}", name=f"Accessory queue {marker}")
        item = Item(
            sku=f"PERF02-{marker}",
            name=f"Accessory {marker}",
            category="accessory",
            unit="pcs",
            composition_json=[],
        )
        db.add_all([model, item])
        db.flush()
        db.add(ModelBOM(
            model_id=model.id,
            item_id=item.id,
            quantity_per_piece=1,
            unit="pcs",
            waste_percent=0,
        ))
        db.add_all([
            ProductionOrder(
                production_no=f"PERF02-{marker}-{number:04d}",
                production_type="branded_stock",
                model_id=model.id,
                planned_quantity=10,
                status="new",
            )
            for number in range(count)
        ])
        db.commit()
        return int(model.id)


@pytest.mark.parametrize("order_count", [1, 50, 401])
def test_accessory_request_page_has_bounded_query_growth(order_count):
    model_id = _accessory_request_orders(order_count)
    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = accessory_issue_requests(
                db,
                model_id=model_id,
                page=1,
                page_size=10,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(rows) == min(order_count, 10)
    assert len(statements) <= 30, f"{order_count} orders issued {len(statements)} SELECTs"


@pytest.mark.parametrize("order_count", [1, 50, 401])
def test_accessory_request_endpoint_pages_candidates_with_bounded_queries(
    client,
    auth_headers,
    monkeypatch,
    order_count,
):
    model_id = _accessory_request_orders(order_count)
    statements: list[str] = []
    candidate_counts: list[int] = []
    original_rows = inventory_service._accessory_request_rows

    def observe_candidate_pages(*args, **kwargs):
        result = original_rows(*args, **kwargs)
        if kwargs.get("include_candidate_count"):
            candidate_counts.append(int(result[1]))
        return result

    monkeypatch.setattr(
        inventory_service,
        "_accessory_request_rows",
        observe_candidate_pages,
    )

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/inventory/accessory-issue-requests",
            params={
                "model_id": model_id,
                "page": 1,
                "page_size": 10,
                "include_total": "true",
            },
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert len(response.json()["rows"]) == min(order_count, 10)
    assert response.json()["total"] == order_count
    print(f"Accessory request endpoint {order_count}: {len(statements)} SELECTs")
    assert len(statements) <= 30
    assert candidate_counts == (
        [order_count]
        if order_count <= inventory_service._BULK_STOCK_CHUNK_SIZE
        else [inventory_service._BULK_STOCK_CHUNK_SIZE, order_count - inventory_service._BULK_STOCK_CHUNK_SIZE]
    )


def test_accessory_request_search_keeps_hyphen_compacted_model_code():
    model_id = _accessory_request_orders(1)
    with TestSessionLocal() as db:
        model = db.get(Model, model_id)
        rows = accessory_issue_requests(
            db,
            q=model.code.replace("-", ""),
            page=1,
            page_size=10,
        )
    assert rows and rows[0]["model_id"] == model_id


def _mixed_accessory_request_case() -> tuple[int, int, str]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF02-MIX-{marker}", name=f"Mixed queue {marker}")
        button = Item(
            sku=f"BUTTON-{marker}",
            name=f"Button {marker}",
            category="accessory",
            unit="pcs",
            composition_json=[],
        )
        carton = Item(
            sku=f"CARTON-{marker}",
            name=f"Carton {marker}",
            category="packaging",
            unit="box",
            composition_json=[],
        )
        db.add_all([model, button, carton])
        db.flush()
        db.add_all([
            ModelBOM(
                model_id=model.id,
                item_id=button.id,
                size="M",
                quantity_per_piece=2,
                unit="pcs",
                waste_percent=0,
            ),
            ModelBOM(
                model_id=model.id,
                item_id=button.id,
                size="L",
                quantity_per_piece=3,
                unit="pcs",
                waste_percent=0,
            ),
            ModelBOM(
                model_id=model.id,
                item_id=carton.id,
                quantity_per_piece=1,
                unit="box",
                waste_percent=0,
            ),
        ])
        sales_order = SalesOrder(
            order_no=f"SO-PERF02-{marker}",
            order_type="client_order",
            status="in_production",
            total_amount=0,
        )
        db.add(sales_order)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF02-MIX-{marker}",
            production_type="branded_stock",
            sales_order_id=sales_order.id,
            model_id=model.id,
            planned_quantity=6,
            status="new",
        )
        db.add(order)
        db.flush()
        db.add_all([
            ProductionOrderItem(
                production_order_id=order.id,
                model_id=model.id,
                color="white",
                size="M",
                planned_quantity=4,
            ),
            ProductionOrderItem(
                production_order_id=order.id,
                model_id=model.id,
                color="black",
                size="L",
                planned_quantity=2,
            ),
        ])
        warehouse = db.query(Warehouse).order_by(Warehouse.id.asc()).first()
        department = db.query(Department).filter(Department.code == "MIL").one()
        batch = StockBatch(
            item_id=button.id,
            batch_no=f"PERF02-MIX-{marker}",
            quantity=12,
            unit="pcs",
            cost_per_unit=1,
            warehouse_id=warehouse.id,
            qc_status="passed",
        )
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department.id,
            operation="cutting",
            status="waiting",
            planned_input_qty=6,
            planned_output_qty=6,
        )
        db.add_all([batch, work_order])
        db.flush()
        db.add_all([
            MaterialReservation(
                reservation_no=f"PERF02-{marker}",
                production_order_id=order.id,
                item_id=button.id,
                stock_batch_id=batch.id,
                warehouse_id=warehouse.id,
                reserved_quantity=2,
                unit="pcs",
                status="reserved",
                reservation_type="accessory",
                source="manual",
            ),
            StockMovement(
                movement_type="issue",
                item_id=button.id,
                batch_id=batch.id,
                from_warehouse_id=warehouse.id,
                quantity=3,
                unit="pcs",
                reference_type="ProductionOrder",
                reference_id=order.id,
            ),
            StockMovement(
                movement_type="consume",
                item_id=button.id,
                batch_id=batch.id,
                from_warehouse_id=warehouse.id,
                quantity=1,
                unit="pcs",
                reference_type="WorkOrder",
                reference_id=work_order.id,
            ),
            StockMovement(
                movement_type="return",
                item_id=button.id,
                batch_id=batch.id,
                to_warehouse_id=warehouse.id,
                quantity=2,
                unit="pcs",
                reference_type="ProductionOrderAccessoryReturn",
                reference_id=order.id,
            ),
            ManualAccessoryIssue(
                production_order_id=order.id,
                item_id=button.id,
                item_sku=button.sku,
                item_name=button.name,
                quantity=0.5,
                unit="pcs",
            ),
            ManualAccessoryIssue(
                production_order_id=order.id,
                item_sku=carton.sku,
                item_name="Legacy carton label",
                quantity=6,
                unit="box",
            ),
        ])
        db.commit()
        return int(model.id), int(order.id), sales_order.order_no


def _scalar_request_rows(db, order_id: int) -> list[dict]:
    order = db.get(ProductionOrder, order_id)
    plan = accessory_issue_plan(db, order_id)
    rows = []
    for row in plan["rows"]:
        remaining = float(row.get("remaining_quantity") or 0)
        rows.append({
            "production_order_id": int(order.id),
            "production_no": order.production_no,
            "order_no": order.order_no,
            "model_id": int(order.model_id),
            "model_code": plan.get("model_code"),
            "model_name": plan.get("model_name"),
            "planned_quantity": int(order.planned_quantity or 0),
            "item_id": int(row["item_id"]),
            "item_sku": row["item_sku"],
            "item_name": row["item_name"],
            "item_image_url": row.get("item_image_url"),
            "category": row["category"],
            "unit": row["unit"],
            "required_quantity": float(row.get("required_quantity") or 0),
            "issued_quantity": float(row.get("issued_quantity") or 0),
            "remaining_quantity": remaining,
            "available_quantity": float(row.get("available_quantity") or 0),
            "shortage": float(row.get("shortage") or 0),
            "status": row["status"],
        })
    return sorted(rows, key=lambda row: (
        0 if row["status"] == "shortage" else 1 if row["status"] == "partial" else 2,
        row["production_order_id"],
        row["item_sku"],
    ))


def test_batched_accessory_requests_match_scalar_plan_for_mixed_evidence():
    model_id, order_id, sales_order_no = _mixed_accessory_request_case()
    with TestSessionLocal() as db:
        expected = _scalar_request_rows(db, order_id)
    with TestSessionLocal() as db:
        actual = accessory_issue_requests(
            db,
            model_id=model_id,
            include_complete=True,
        )
        incomplete = accessory_issue_requests(db, production_order_id=order_id)

    assert actual == expected
    assert [row["status"] for row in actual] == ["partial", "ready"]
    assert {row["order_no"] for row in actual} == {sales_order_no}
    assert actual[0]["issued_quantity"] == 4.5
    assert incomplete == [expected[0]]


def test_accessory_request_api_preserves_total_and_empty_page(client, auth_headers):
    model_id = _accessory_request_orders(3)
    with TestSessionLocal() as db:
        item_sku = (
            db.query(Item.sku)
            .join(ModelBOM, ModelBOM.item_id == Item.id)
            .filter(ModelBOM.model_id == model_id)
            .scalar()
        )
    first = client.get(
        "/api/inventory/accessory-issue-requests",
        params={"model_id": model_id, "page": 1, "page_size": 2, "include_total": "true"},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    assert len(first.json()["rows"]) == 2
    assert first.json()["total"] == 3
    assert all(row["order_no"] == row["production_no"] for row in first.json()["rows"])

    empty = client.get(
        "/api/inventory/accessory-issue-requests",
        params={"model_id": model_id, "page": 3, "page_size": 2, "include_total": "true"},
        headers=auth_headers,
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["rows"] == []
    assert empty.json()["total"] == 3

    matching = client.get(
        "/api/inventory/accessory-issue-requests",
        params={"model_id": model_id, "q": item_sku, "include_total": "true"},
        headers=auth_headers,
    )
    assert matching.status_code == 200, matching.text
    assert matching.json()["total"] == 3

    missing = client.get(
        "/api/inventory/accessory-issue-requests",
        params={"model_id": model_id, "q": "no-such-accessory", "include_total": "true"},
        headers=auth_headers,
    )
    assert missing.status_code == 200, missing.text
    assert missing.json()["rows"] == []
    assert missing.json()["total"] == 0


def test_accessory_request_candidate_chunk_boundary_preserves_legacy_pages(
    client,
    auth_headers,
    monkeypatch,
):
    model_id = _accessory_request_orders(51)
    monkeypatch.setattr(inventory_service, "_BULK_STOCK_CHUNK_SIZE", 20)
    with TestSessionLocal() as db:
        expected = accessory_issue_requests(
            db,
            model_id=model_id,
        )

    second = client.get(
        "/api/inventory/accessory-issue-requests",
        params={
            "model_id": model_id,
            "page": 2,
            "page_size": 20,
            "include_total": "true",
        },
        headers=auth_headers,
    )
    final_legacy = client.get(
        "/api/inventory/accessory-issue-requests",
        params={"model_id": model_id, "page": 3, "page_size": 20},
        headers=auth_headers,
    )
    beyond = client.get(
        "/api/inventory/accessory-issue-requests",
        params={
            "model_id": model_id,
            "page": 4,
            "page_size": 20,
            "include_total": "true",
        },
        headers=auth_headers,
    )

    assert second.status_code == 200, second.text
    assert second.json() == {
        "rows": expected[20:40],
        "total": 51,
        "page": 2,
        "page_size": 20,
    }
    assert final_legacy.status_code == 200, final_legacy.text
    assert final_legacy.json() == expected[40:]
    assert beyond.status_code == 200, beyond.text
    assert beyond.json() == {
        "rows": [],
        "total": 51,
        "page": 4,
        "page_size": 20,
    }


def test_accessory_request_status_order_is_global_across_candidate_chunks(
    client,
    auth_headers,
    monkeypatch,
):
    model_id = _accessory_request_orders(2)
    monkeypatch.setattr(inventory_service, "_BULK_STOCK_CHUNK_SIZE", 1)
    with TestSessionLocal() as db:
        orders = (
            db.query(ProductionOrder)
            .filter(ProductionOrder.model_id == model_id)
            .order_by(ProductionOrder.id)
            .all()
        )
        item = (
            db.query(Item)
            .join(ModelBOM, ModelBOM.item_id == Item.id)
            .filter(ModelBOM.model_id == model_id)
            .one()
        )
        db.add(ManualAccessoryIssue(
            production_order_id=orders[0].id,
            item_id=item.id,
            item_sku=item.sku,
            item_name=item.name,
            quantity=10,
            unit="pcs",
        ))
        db.commit()
        ready_order_id = int(orders[0].id)
        shortage_order_id = int(orders[1].id)

    first = client.get(
        "/api/inventory/accessory-issue-requests",
        params={
            "model_id": model_id,
            "include_complete": "true",
            "include_total": "true",
            "page": 1,
            "page_size": 1,
        },
        headers=auth_headers,
    )
    second = client.get(
        "/api/inventory/accessory-issue-requests",
        params={
            "model_id": model_id,
            "include_complete": "true",
            "include_total": "true",
            "page": 2,
            "page_size": 1,
        },
        headers=auth_headers,
    )

    assert first.status_code == 200, first.text
    assert first.json()["total"] == 2
    assert first.json()["rows"][0]["status"] == "shortage"
    assert first.json()["rows"][0]["production_order_id"] == shortage_order_id
    assert second.status_code == 200, second.text
    assert second.json()["rows"][0]["status"] == "ready"
    assert second.json()["rows"][0]["production_order_id"] == ready_order_id


def test_accessory_request_endpoint_matches_scalar_alias_and_completion_filters(
    client,
    auth_headers,
):
    model_id, order_id, _sales_order_no = _mixed_accessory_request_case()
    with TestSessionLocal() as db:
        model = db.get(Model, model_id)
        expected_all = accessory_issue_requests(
            db,
            production_order_id=order_id,
            include_complete=True,
        )
        expected_incomplete = accessory_issue_requests(
            db,
            production_order_id=order_id,
        )

    compact_code = model.code.replace("-", "")
    all_rows = client.get(
        "/api/inventory/accessory-issue-requests",
        params={
            "production_order_id": order_id,
            "q": compact_code,
            "include_complete": "true",
            "include_total": "true",
            "page_size": 10,
        },
        headers=auth_headers,
    )
    incomplete = client.get(
        "/api/inventory/accessory-issue-requests",
        params={
            "production_order_id": order_id,
            "include_total": "true",
            "page_size": 10,
        },
        headers=auth_headers,
    )

    assert all_rows.status_code == 200, all_rows.text
    assert all_rows.json()["rows"] == expected_all
    assert all_rows.json()["total"] == len(expected_all)
    assert incomplete.status_code == 200, incomplete.text
    assert incomplete.json()["rows"] == expected_incomplete
    assert incomplete.json()["total"] == len(expected_incomplete)


def test_accessory_request_endpoint_denies_missing_and_unrelated_permissions(client):
    model_id = _accessory_request_orders(1)
    path = f"/api/inventory/accessory-issue-requests?model_id={model_id}"

    assert client.get(path).status_code == 401
    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        path,
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403
    with TestSessionLocal() as db:
        assert db.query(ProductionOrder).filter(ProductionOrder.model_id == model_id).count() == 1

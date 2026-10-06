from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event

from app.core.costs import round_unit_cost
from app.db.session import SessionLocal
from app.models import (
    AuditLog, IdempotencyRecord, Item, Model, ProductionOrder, PurchaseOrder,
    PurchaseOrderLine, StockBatch, StockMovement, User, Warehouse,
)
from app.schemas.inventory import AccessoryReturnIn, ItemIn, StockBatchIn, StockBatchUpdate
from app.schemas.purchasing import PurchaseOrderLineIn, PurchaseOrderReceiveLineIn
from app.services.idempotency import request_fingerprint
from app.services.purchasing import create_purchase_order, receive_purchase_order


INVALID_COSTS = [-0.00001, "NaN", "Infinity", "-Infinity", True, False,
                 "invalid", {}, "100000000", "99999999.99995", "1e1000"]


@pytest.mark.parametrize("value,expected", [
    ("1.23445", "1.2345"), (1.23445, "1.2345"), ("1.23444", "1.2344"),
    ("0.00005", "0.0001"), ("0.00004", "0.0000"), (0, "0.0000"),
    ("99999999.99994", "99999999.9999"),
])
def test_unit_cost_half_up_storage_policy(value, expected):
    assert round_unit_cost(value) == Decimal(expected)


SCHEMA_CASES = [
    (ItemIn, "default_cost", {"sku": "COST", "name": "Cost", "category": "fabric", "unit": "kg"}),
    (StockBatchIn, "cost_per_unit", {"item_id": 1, "batch_no": "COST", "quantity": 1, "unit": "kg", "warehouse_id": 1}),
    (StockBatchUpdate, "cost_per_unit", {}),
    (AccessoryReturnIn, "cost_per_unit", {"production_order_id": 1, "item_id": 1, "batch_no": "COST", "quantity": 1, "unit": "pcs", "warehouse_id": 1}),
    (PurchaseOrderLineIn, "unit_cost", {"item_id": 1, "ordered_quantity": 1}),
    (PurchaseOrderReceiveLineIn, "cost_per_unit", {"purchase_order_line_id": 1, "received_quantity": 1, "batch_no": "COST"}),
]


@pytest.mark.parametrize("model,field,payload", SCHEMA_CASES)
@pytest.mark.parametrize("value", INVALID_COSTS)
def test_cost_input_rejects_invalid_before_rounding(model, field, payload, value):
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: value})
    with pytest.raises(ValueError):
        round_unit_cost(value)


@pytest.mark.parametrize("model,field,payload", SCHEMA_CASES)
def test_cost_input_retains_extra_precision_until_persistence(model, field, payload):
    assert getattr(model.model_validate({**payload, field: "1.23445"}), field) == Decimal("1.23445")
    assert getattr(model.model_validate({**payload, field: "99999999.99994"}), field) == Decimal("99999999.99994")


def _item_payload(**overrides):
    token = uuid4().hex
    return {"sku": f"COST-{token}", "name": f"Cost {token}", "category": "fabric",
            "unit": "kg", "default_cost": "1.23445", "track_batch": True, **overrides}


@pytest.fixture
def cost_case():
    with SessionLocal() as db:
        item = db.query(Item).filter(Item.category == "fabric").first()
        warehouse = db.query(Warehouse).filter(Warehouse.type == "fabric_storage").first()
        user = db.query(User).filter(User.email == "admin@example.com").one()
        order = PurchaseOrder(po_no=f"COST-{uuid4().hex}", status="sent", ordered_by=user.id)
        db.add(order)
        db.flush()
        lines = [PurchaseOrderLine(purchase_order_id=order.id, item_id=item.id, unit=item.unit,
                                 ordered_quantity=10, received_quantity=0, unit_cost=Decimal("2.3456"),
                                 warehouse_id=warehouse.id) for _ in range(2)]
        db.add_all(lines)
        db.commit()
        return {"item_id": item.id, "unit": item.unit, "warehouse_id": warehouse.id,
                "user_id": user.id, "order_id": order.id, "line_ids": [line.id for line in lines]}


def _receipt(case, **overrides):
    return {"item_id": case["item_id"], "batch_no": f"COST-{uuid4().hex}", "quantity": 1,
            "unit": case["unit"], "warehouse_id": case["warehouse_id"], "cost_per_unit": "1.23445",
            "qc_status": "passed", **overrides}


def _purchase_receipt(case, index=0, **overrides):
    return {"purchase_order_line_id": case["line_ids"][index], "received_quantity": 1,
            "batch_no": f"COST-{uuid4().hex}", "cost_per_unit": "1.23445", **overrides}


def _counts(db):
    return tuple(db.query(model).count() for model in (
        Item, PurchaseOrder, PurchaseOrderLine, StockBatch, StockMovement, AuditLog, IdempotencyRecord,
    ))


def test_item_create_update_and_adjustment_batch_store_rounded_cost(client, auth_headers):
    payload = _item_payload()
    created = client.post("/api/inventory/items", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    with SessionLocal() as db:
        assert db.get(Item, item_id).default_cost == Decimal("1.2345")
    updated = client.patch(f"/api/inventory/items/{item_id}", headers=auth_headers,
                           json={**payload, "default_cost": "2.34565"})
    assert updated.status_code == 200, updated.text
    adjusted = client.patch(f"/api/inventory/stock/{item_id}", headers=auth_headers, json={"quantity": 1})
    assert adjusted.status_code == 200, adjusted.text
    with SessionLocal() as db:
        assert db.get(Item, item_id).default_cost == Decimal("2.3457")
        assert db.query(StockBatch).filter_by(item_id=item_id).one().cost_per_unit == Decimal("2.3457")


def test_stock_receive_and_patch_store_rounded_cost(client, auth_headers, cost_case):
    received = client.post("/api/inventory/receive", headers=auth_headers, json=_receipt(cost_case))
    assert received.status_code == 201, received.text
    batch_id = received.json()["id"]
    with SessionLocal() as db:
        assert db.get(StockBatch, batch_id).cost_per_unit == Decimal("1.2345")
    patched = client.patch(f"/api/inventory/batches/{batch_id}", headers=auth_headers,
                           json={"cost_per_unit": "2.34565"})
    assert patched.status_code == 200, patched.text
    with SessionLocal() as db:
        assert db.get(StockBatch, batch_id).cost_per_unit == Decimal("2.3457")


def test_purchase_create_receive_and_null_fallback_store_rounded_cost(client, auth_headers, cost_case):
    case = cost_case
    created = client.post("/api/purchasing/orders", headers=auth_headers, json={"lines": [{
        "item_id": case["item_id"], "ordered_quantity": 10, "unit_cost": "1.23445",
        "warehouse_id": case["warehouse_id"],
    }]})
    assert created.status_code == 201, created.text
    order_id, line_id = created.json()["id"], created.json()["lines"][0]["id"]
    with SessionLocal() as db:
        assert db.get(PurchaseOrderLine, line_id).unit_cost == Decimal("1.2345")
        db.get(PurchaseOrder, order_id).status = "sent"
        db.commit()
    for cost, expected in [("2.34565", "2.3457"), (None, "2.3457")]:
        batch_no = f"COST-{uuid4().hex}"
        received = client.post(f"/api/purchasing/orders/{order_id}/receive", headers=auth_headers,
                               json={"lines": [{"purchase_order_line_id": line_id,
                                     "received_quantity": 1, "batch_no": batch_no, "cost_per_unit": cost}]})
        assert received.status_code == 200, received.text
        with SessionLocal() as db:
            assert db.query(StockBatch).filter_by(batch_no=batch_no).one().cost_per_unit == Decimal(expected)
            assert db.get(PurchaseOrderLine, line_id).unit_cost == Decimal(expected)


def test_accessory_return_stores_rounded_cost(client, auth_headers):
    with SessionLocal() as db:
        item = db.query(Item).filter_by(category="accessory").first()
        warehouse = db.query(Warehouse).filter_by(type="accessory_storage").first()
        model = db.query(Model).first()
        order = ProductionOrder(production_no=f"COST-{uuid4().hex}", model_id=model.id,
                                production_type="branded_stock", planned_quantity=1)
        db.add(order)
        db.flush()
        db.add(StockMovement(movement_type="consume", item_id=item.id, quantity=1, unit=item.unit,
                            reference_type="ProductionOrder", reference_id=order.id))
        db.commit()
        payload = {"production_order_id": order.id, "item_id": item.id, "quantity": 1,
                   "unit": item.unit, "warehouse_id": warehouse.id, "batch_no": f"COST-{uuid4().hex}",
                   "cost_per_unit": "1.23445", "qc_status": "passed"}
    received = client.post("/api/inventory/accessory-returns", headers=auth_headers, json=payload)
    assert received.status_code == 201, received.text
    with SessionLocal() as db:
        assert db.get(StockBatch, received.json()["id"]).cost_per_unit == Decimal("1.2345")


@pytest.mark.parametrize("value", [-0.00001, True, "NaN", "Infinity", "99999999.99995"])
def test_invalid_api_costs_do_not_write_and_preserve_authentication(client, auth_headers, cost_case, value):
    case = cost_case
    received = client.post("/api/inventory/receive", headers=auth_headers, json=_receipt(case))
    assert received.status_code == 201, received.text
    item_payload = _item_payload(default_cost=value)
    endpoints = [
        ("post", "/api/inventory/items", item_payload),
        ("patch", f"/api/inventory/items/{case['item_id']}", item_payload),
        ("post", "/api/inventory/receive", _receipt(case, cost_per_unit=value)),
        ("patch", f"/api/inventory/batches/{received.json()['id']}", {"cost_per_unit": value}),
        ("post", "/api/purchasing/orders", {"lines": [{"item_id": case["item_id"], "ordered_quantity": 1, "unit_cost": value}]}),
        ("post", f"/api/purchasing/orders/{case['order_id']}/receive", {"lines": [_purchase_receipt(case, cost_per_unit=value)]}),
        ("post", "/api/inventory/accessory-returns", {**_receipt(case, cost_per_unit=value), "production_order_id": 1}),
    ]
    with SessionLocal() as db:
        before = _counts(db)
    for method, path, payload in endpoints:
        rejected = getattr(client, method)(path, headers=auth_headers, json=payload)
        assert rejected.status_code == 422, (path, rejected.text)
        unauthorized = getattr(client, method)(path, json=payload)
        assert unauthorized.status_code == 401, (path, unauthorized.text)
        with SessionLocal() as db:
            assert _counts(db) == before
            assert db.get(PurchaseOrderLine, case["line_ids"][0]).received_quantity == 0
            assert db.get(StockBatch, received.json()["id"]).cost_per_unit == Decimal("1.2345")


@pytest.mark.parametrize("value", INVALID_COSTS)
@pytest.mark.parametrize("operation", ["create", "receive"])
def test_direct_services_reject_invalid_second_cost_without_partial_writes(cost_case, value, operation):
    case = cost_case
    with SessionLocal() as db:
        before = _counts(db)
        user = db.get(User, case["user_id"])
        with pytest.raises(HTTPException) as error:
            if operation == "create":
                line = {"item_id": case["item_id"], "ordered_quantity": 1, "unit_cost": "1.23445"}
                create_purchase_order(db, data={"lines": [line, {**line, "unit_cost": value}]}, current=user)
            else:
                receive_purchase_order(db, order_id=case["order_id"], data={"lines": [
                    _purchase_receipt(case), _purchase_receipt(case, 1, cost_per_unit=value),
                ]}, current=user)
        assert error.value.status_code == 400
        db.commit()  # A caller catching validation errors must not commit partial work.
        assert _counts(db) == before
        assert db.get(PurchaseOrder, case["order_id"]).status == "sent"
        for line_id in case["line_ids"]:
            line = db.get(PurchaseOrderLine, line_id)
            assert line.received_quantity == 0
            assert line.unit_cost == Decimal("2.3456")


def test_direct_services_use_decimal_before_flush(cost_case):
    case = cost_case
    captured = []
    with SessionLocal() as db:
        def capture_costs(session, flush_context, instances):
            for row in session.new:
                if isinstance(row, PurchaseOrderLine):
                    captured.append(row.unit_cost)
                elif isinstance(row, StockBatch):
                    captured.append(row.cost_per_unit)
        event.listen(db, "before_flush", capture_costs)
        user = db.get(User, case["user_id"])
        create_purchase_order(db, current=user, data={"lines": [{"item_id": case["item_id"],
                              "ordered_quantity": 1, "unit_cost": "1.23445"}]})
        receive_purchase_order(db, current=user, order_id=case["order_id"],
                               data={"lines": [_purchase_receipt(case)]})
        assert captured == [Decimal("1.2345"), Decimal("1.2345")]
        assert all(isinstance(value, Decimal) for value in captured)


def test_repeated_purchase_line_receipts_keep_prior_explicit_cost_fallback(cost_case):
    case = cost_case
    lines = [_purchase_receipt(case), _purchase_receipt(case, cost_per_unit=None)]
    with SessionLocal() as db:
        receive_purchase_order(db, current=db.get(User, case["user_id"]), order_id=case["order_id"],
                               data={"lines": lines})
        db.commit()
        batches = db.query(StockBatch).filter(StockBatch.batch_no.in_([line["batch_no"] for line in lines])).all()
        assert len(batches) == 2
        assert all(batch.cost_per_unit == Decimal("1.2345") for batch in batches)


@pytest.mark.parametrize("cost", [None, 1.23445, "1.23445"])
def test_receipt_replays_legacy_float_fingerprint_without_duplicate_stock(client, auth_headers, cost_case, cost):
    payload = _receipt(cost_case)
    if cost is None:
        payload.pop("cost_per_unit")
    else:
        payload["cost_per_unit"] = cost
    key = f"cost-{uuid4().hex}"
    headers = {**auth_headers, "Idempotency-Key": key}
    created = client.post("/api/inventory/receive", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    # Reconstruct the old float schema's payload rather than hashing rounded cost.
    legacy_payload = StockBatchIn.model_validate(payload).model_dump(mode="json")
    legacy_payload["cost_per_unit"] = 0 if cost is None else float(cost)
    legacy_payload.pop("length_m")
    legacy_payload.pop("roll_lengths_m")
    with SessionLocal() as db:
        record = db.query(IdempotencyRecord).filter_by(key=key).one()
        assert record.scope.startswith("inventory.receive:v2:")
        assert record.request_hash == request_fingerprint(legacy_payload)
        before = _counts(db)
    replay = client.post("/api/inventory/receive", headers=headers, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == created.json()["id"]
    with SessionLocal() as db:
        assert _counts(db) == before

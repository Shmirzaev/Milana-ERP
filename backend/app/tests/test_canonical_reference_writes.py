import pytest

from app.db.session import SessionLocal
from app.models import IdempotencyRecord, Item, ProductionOrder, PurchaseOrder, StockBatch, Warehouse
from app.models.cutting_passport import CuttingPassport
from app.models.order_reference import BusinessOrderAlias
from app.tests.test_production_flow import _create_bundle_for_scan
from app.tests.test_purchasing import _create_approved_purchase_order


def _legacy_production(client, headers):
    bundle = _create_bundle_for_scan(client, headers)
    with SessionLocal() as db:
        order = db.get(ProductionOrder, bundle["production_order_id"])
        order.production_no = "PO-0202"
        db.add(BusinessOrderAlias(namespace="PO", entity_id=order.id,
                                  reference="PO-2026-000202", canonical_reference="PO-0202"))
        db.commit()
        return order.id, order.order_no


def test_linked_passport_create_and_update_ignore_stale_order_text(client, auth_headers):
    order_id, public_no = _legacy_production(client, auth_headers)
    body = {"passport_no": "PASSPORT-UNCHANGED", "date": "2026-09-09T00:00:00",
            "production_order_id": order_id, "order_no": "PO-2026-000202"}
    created = client.post("/api/cutting-passports", json=body, headers=auth_headers)
    assert created.status_code == 201, created.text
    passport_id = created.json()["id"]
    body["order_no"] = "OTHER-ORDER-999"
    updated = client.patch(f"/api/cutting-passports/{passport_id}", json=body, headers=auth_headers)
    assert updated.status_code == 200, updated.text
    with SessionLocal() as db:
        passport = db.get(CuttingPassport, passport_id)
        assert passport.order_no == public_no
        assert passport.passport_no == "PASSPORT-UNCHANGED"


@pytest.mark.parametrize("submitted,expected", [
    ("PO-2026-000202", "PO-0202"),
    ("CUSTOMER/LOT-2026-000202", "CUSTOMER/LOT-2026-000202"),
    ("PO-2026-999999", "PO-2026-999999"),
])
def test_unlinked_passport_and_stock_resolve_only_known_aliases(client, auth_headers, submitted, expected):
    _legacy_production(client, auth_headers)
    body = {"passport_no": "UNLINKED-PASSPORT", "date": "2026-09-09T00:00:00", "order_no": submitted}
    response = client.post("/api/cutting-passports", json=body, headers=auth_headers)
    assert response.status_code == 201, response.text
    assert response.json()["order_no"] == expected
    with SessionLocal() as db:
        item = db.query(Item).filter_by(category="fabric").first()
        warehouse = db.query(Warehouse).filter_by(type="fabric_storage").first()
        stock = {"item_id": item.id, "batch_no": "SUPPLIER-LOT-UNCHANGED", "order_no": submitted,
                 "warehouse_id": warehouse.id, "quantity": 1, "unit": item.unit}
    response = client.post("/api/inventory/receive", json=stock, headers=auth_headers)
    assert response.status_code == 201, response.text
    batch_id = response.json()["id"]
    assert response.json()["order_no"] == expected
    # An edit made from an older browser form resolves the same exact alias.
    response = client.patch(f"/api/inventory/batches/{batch_id}", json={"order_no": submitted}, headers=auth_headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        assert batch.order_no == expected
        assert batch.batch_no == "SUPPLIER-LOT-UNCHANGED"


def test_purchase_receipt_uses_live_internal_number_and_resolves_optional_order_alias(client, auth_headers):
    order = _create_approved_purchase_order(client, auth_headers)
    with SessionLocal() as db:
        purchase = db.get(PurchaseOrder, order["id"])
        purchase.po_no = "PUR-0202"
        db.add(BusinessOrderAlias(namespace="PUR", entity_id=purchase.id,
                                  reference="PUR-2026-000202", canonical_reference="PUR-0202"))
        db.commit()
        warehouse_id = db.query(Warehouse).filter_by(type="fabric_storage").first().id
    line = next(line for line in order["lines"] if line["item_sku"] == "FAB-COT-001")
    response = client.post(f"/api/purchasing/orders/{order['id']}/receive", headers=auth_headers, json={
        "lines": [{"purchase_order_line_id": line["id"], "received_quantity": 1,
                   "batch_no": "SUPPLIER-ORIGINAL-LOT", "warehouse_id": warehouse_id,
                   "order_no": "PUR-2026-000202"}],
    })
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        batch = db.query(StockBatch).filter_by(batch_no="SUPPLIER-ORIGINAL-LOT").one()
        assert batch.internal_batch_no == batch.order_no == "PUR-0202"


def test_stock_replay_renders_canonical_number_without_rewriting_snapshot_or_creating_stock(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    with SessionLocal() as db:
        order = db.get(ProductionOrder, bundle["production_order_id"])
        order.production_no = "PO-2026-000202"
        db.commit()
        item = db.query(Item).filter_by(category="fabric").first()
        warehouse = db.query(Warehouse).filter_by(type="fabric_storage").first()
        body = {"item_id": item.id, "batch_no": "REPLAY-LOT", "order_no": order.production_no,
                "warehouse_id": warehouse.id, "quantity": 1, "unit": item.unit}
    headers = {**auth_headers, "Idempotency-Key": "canonical-stock-replay"}
    first = client.post("/api/inventory/receive", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert first.json()["order_no"] == "PO-2026-000202"
    with SessionLocal() as db:
        order = db.get(ProductionOrder, bundle["production_order_id"])
        order.production_no = "PO-0202"
        db.add(BusinessOrderAlias(namespace="PO", entity_id=order.id,
                                  reference="PO-2026-000202", canonical_reference="PO-0202"))
        db.commit()
        record = db.query(IdempotencyRecord).filter_by(key="canonical-stock-replay").one()
        original_hash, original_snapshot = record.request_hash, dict(record.response_json)
        stock_count = db.query(StockBatch).count()
    replay = client.post("/api/inventory/receive", json=body, headers=headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["order_no"] == "PO-0202"
    assert client.post("/api/inventory/receive", json={**body, "quantity": 2}, headers=headers).status_code == 409
    with SessionLocal() as db:
        record = db.query(IdempotencyRecord).filter_by(key="canonical-stock-replay").one()
        assert record.request_hash == original_hash and record.response_json == original_snapshot
        assert db.query(StockBatch).count() == stock_count

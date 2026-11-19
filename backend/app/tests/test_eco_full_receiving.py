"""Operator receipts retain full details and never bypass quality or factory balances."""
from decimal import Decimal
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.core.security import create_access_token
from app.libs.dto.inventory.eco_inventory_input import EcoMaterialReceiveIn, EcoMaterialConsumeIn, EcoQualityIn, EcoWarehouseIn
from app.libs.dto.inventory.item_input import ItemIn
from app.models.inventory import eco_inventory_service as eco
from app.models.inventory import stock_service
from app.schemas import Supplier, Item
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.tests.test_eco_inventory_transfers import setup_materials, actor  # noqa: F401


def receipt(scenario, **changes):
    db, user, item, _, _ = scenario
    actor(db, user, "ECO")
    return EcoMaterialReceiveIn(request_key="full-receipt", item_id=item.id, kind="fabric", batch_no="OPENING-01",
        quantity="12.5000", **changes)


def test_full_opening_stock_receipt_retains_details_and_replays_once(setup_materials):
    db, user, _, _, milana_batch = setup_materials
    actor(db, user, "ECO")
    supplier = Supplier(name="ECO receipt supplier")
    db.add(supplier); db.commit()
    warehouse = eco.create_warehouse(db, user, EcoWarehouseIn(name="ECO fabric room", kind="fabric"))
    payload = receipt(setup_materials, source="opening_balance", supplier_id=supplier.id, warehouse_id=warehouse.id,
        unit="kg", cost_per_unit="2.1250", received_date="2026-11-03T00:00:00+05:00", document_no="OPEN-2026",
        piece_count=2, roll_weights_kg=["5.25", "7.25"], roll_lengths_m=["20", None], width="180", gsm="0.18",
        old_code="OLD-1", color_code="C-1", processes="Dyed", notes="Physical opening count")
    result = eco.receive_stock(db, payload, user)
    assert eco.receive_stock(db, payload, user) == result
    batch = db.get(EcoMaterialBatch, result.batch.id)
    assert batch.receipt_details["source"] == "opening_balance"
    assert batch.receipt_details["warehouse_name"] == "ECO fabric room"
    assert batch.receipt_details["supplier_name"] == supplier.name
    assert batch.receipt_details["roll_weights_kg"] == ["5.25", "7.25"]
    assert result.batch.receipt_details.cost_per_unit == Decimal("2.1250")
    assert db.query(EcoMaterialMovement).filter_by(batch_id=batch.id).count() == 1
    assert milana_batch.quantity == 100


def test_pending_quality_is_visible_but_cannot_be_consumed(setup_materials):
    db, user, *_ = setup_materials
    result = eco.receive_stock(db, receipt(setup_materials, qc_status="pending"), user)
    assert result.batch.quantity == Decimal("12.5") and result.batch.available_quantity == 0
    with pytest.raises(HTTPException, match="quality inspection"):
        eco.consume_stock(db, EcoMaterialConsumeIn(request_key="pending-consume", batch_id=result.batch.id, quantity="1"), user)
    db.rollback()
    approved = eco.update_quality(db, user, result.batch.id, EcoQualityIn(qc_status="passed"))
    assert approved.available_quantity == Decimal("12.5")
    eco.consume_stock(db, EcoMaterialConsumeIn(request_key="passed-consume", batch_id=result.batch.id, quantity="1"), user)
    assert db.get(EcoMaterialBatch, result.batch.id).quantity == Decimal("11.5")


def test_milana_warehouse_cannot_receive_eco_stock(setup_materials):
    db, user, _, _, milana = setup_materials
    payload = receipt(setup_materials, warehouse_id=milana.warehouse_id)
    with pytest.raises(HTTPException) as failure:
        eco.receive_stock(db, payload, user)
    assert failure.value.status_code == 403 and db.query(EcoMaterialBatch).count() == 0


def test_roll_totals_and_accessory_unit_are_enforced(setup_materials):
    db, user, _, accessory, _ = setup_materials
    with pytest.raises(ValidationError, match="Roll count and total"):
        receipt(setup_materials, unit="kg", piece_count=2, roll_weights_kg=["5", "5"])
    actor(db, user, "ECO")
    with pytest.raises(HTTPException, match="catalog unit"):
        eco.receive_stock(db, EcoMaterialReceiveIn(request_key="wrong-unit", item_id=accessory.id,
            kind="accessory", batch_no="A-01", quantity="10", unit="kg"), user)


def test_allocated_batch_cannot_be_placed_on_hold(setup_materials):
    db, user, *_ = setup_materials
    result = eco.receive_stock(db, receipt(setup_materials), user)
    batch = db.get(EcoMaterialBatch, result.batch.id)
    batch.reserved_quantity = 1; db.commit()
    with pytest.raises(HTTPException, match="Release approved"):
        eco.update_quality(db, user, batch.id, EcoQualityIn(qc_status="hold"))
    assert batch.receipt_details["qc_status"] == "passed"


def test_eco_stock_protects_shared_catalog_identity_and_deletion(setup_materials):
    db, user, item, *_ = setup_materials
    eco.receive_stock(db, receipt(setup_materials), user)
    with pytest.raises(HTTPException, match="unit/category"):
        stock_service.update_item(db, item.id, ItemIn(sku=item.sku, name=item.name, category="fabric", unit="m"), user)
    with pytest.raises(HTTPException) as refusal:
        stock_service.delete_item(db, item.id, user)
    assert refusal.value.status_code == 409
    assert db.get(Item, item.id) is not None


def test_catalog_create_is_available_to_authorized_eco_user(client, setup_materials):
    db, user, *_ = setup_materials
    headers = {"Authorization": "Bearer " + create_access_token(user.id, extra={"factory_code": "ECO"})}
    response = client.post("/api/inventory/items", headers=headers, json={
        "sku": "ECO-CATALOG-BUTTON", "name": "New ECO button type", "category": "accessory", "unit": "pcs",
        "composition": [], "track_batch": True})
    assert response.status_code == 201, response.text
    options = client.get("/api/eco-inventory/items?kind=accessory", headers=headers)
    assert options.status_code == 200
    assert any(row["id"] == response.json()["id"] for row in options.json())


def test_stock_search_applies_before_pagination(setup_materials):
    db, user, item, *_ = setup_materials
    eco.receive_stock(db, receipt(setup_materials), user)
    for index in range(3):
        db.add(EcoMaterialBatch(item_id=item.id, kind="fabric", batch_no=f"OTHER-{index}",
            unit="kg", quantity=1, reserved_quantity=0, created_by=user.id))
    db.commit()
    found = eco.list_stock(db, user, limit=1, q="OPENING-01")
    assert len(found) == 1 and found[0].batch_no == "OPENING-01"


def test_transfer_receipt_uses_dispatched_cost_and_fabric_snapshot(setup_materials):
    from app.tests.test_eco_inventory_transfers import dispatch, receipt as accept
    db, user, _, _, milana = setup_materials
    milana.cost_per_unit = Decimal("3.25"); milana.old_code = "MIL-SOURCE"; db.commit()
    sent = dispatch(db, user, milana)
    milana.cost_per_unit = Decimal("9"); db.commit()
    accept(db, user, sent, "10")
    batch = db.query(EcoMaterialBatch).one()
    assert Decimal(batch.receipt_details["cost_per_unit"]) == Decimal("3.25")
    assert batch.receipt_details["old_code"] == "MIL-SOURCE"
    assert batch.receipt_details["document_no"] == f"MEC-{sent.id:06d}"

"""Atomic multi-row ECO receiving: stock, shared metadata, refusal and retry recovery."""
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.libs.dto.inventory.eco_inventory_input import EcoMaterialBulkReceiveIn
from app.models.inventory import eco_inventory_service as eco
from app.schemas import Item, StockBatch
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.tests.test_eco_inventory_transfers import setup_materials, actor  # noqa: F401


def payload(item, accessory, **patch):
    return EcoMaterialBulkReceiveIn(request_key="table-receipt", lines=[
        {"kind": "fabric", "item_id": item.id, "batch_no": "NEW-LOT-A", "quantity": "1.3", "unit": "kg", "color": "Red", "gsm": "220"},
        {"kind": "accessory", "item_id": accessory.id, "batch_no": "NEW-LOT-B", "quantity": "12", "unit": "pcs"},
    ], **patch)


def test_bulk_receipt_replay_persists_two_rows_once_and_leaves_milana_untouched(setup_materials):
    db, user, item, accessory, central = setup_materials
    actor(db, user, "ECO")
    request = payload(item, accessory)
    result = eco.receive_stock_bulk(db, request, user)
    replay = eco.receive_stock_bulk(db, request, user)
    assert [r.batch.id for r in replay] == [r.batch.id for r in result]
    assert db.query(EcoMaterialBatch).count() == db.query(EcoMaterialMovement).count() == 2
    assert db.get(StockBatch, central.id).quantity == Decimal("100")
    assert result[0].batch.receipt_details.gsm == Decimal("220")
    assert result[1].batch.quantity == Decimal("12")


def test_invalid_second_row_rollback_removes_first_row_and_retry_can_succeed(setup_materials):
    db, user, item, accessory, _ = setup_materials
    actor(db, user, "ECO")
    request = payload(item, accessory)
    invalid = request.model_copy(deep=True)
    invalid.lines[1].item_id = 999999999
    with pytest.raises(HTTPException) as exc:
        eco.receive_stock_bulk(db, invalid, user)
    assert exc.value.status_code == 400
    db.rollback()
    assert db.query(EcoMaterialBatch).count() == db.query(EcoMaterialMovement).count() == 0
    assert len(eco.receive_stock_bulk(db, request, user)) == 2


def test_bulk_changed_retry_refused_without_extra_stock(setup_materials):
    db, user, item, accessory, _ = setup_materials
    actor(db, user, "ECO")
    request = payload(item, accessory)
    eco.receive_stock_bulk(db, request, user)
    request.lines[0].quantity = Decimal("99")
    with pytest.raises(HTTPException) as exc:
        eco.receive_stock_bulk(db, request, user)
    assert exc.value.status_code == 409
    assert sum(row.quantity for row in db.query(EcoMaterialBatch)) == Decimal("13.3")


def test_bulk_same_fabric_different_lots_keeps_batch_identity(setup_materials):
    db, user, item, accessory, _ = setup_materials
    actor(db, user, "ECO")
    request = payload(item, accessory)
    request.lines[1] = request.lines[0].model_copy(update={"batch_no": "NEW-LOT-B", "quantity": Decimal("2")})
    result = eco.receive_stock_bulk(db, request, user)
    assert [r.batch.batch_no for r in result] == ["NEW-LOT-A", "NEW-LOT-B"]
    assert [r.batch.item_id for r in result] == [item.id, item.id]
    assert sum(row.quantity for row in db.query(EcoMaterialBatch)) == Decimal("3.3")


def test_bulk_non_eco_factory_is_refused_before_writes(setup_materials):
    db, user, item, accessory, _ = setup_materials
    actor(db, user, "MIL")
    with pytest.raises(HTTPException) as exc:
        eco.receive_stock_bulk(db, payload(item, accessory), user)
    assert exc.value.status_code == 403
    assert db.query(EcoMaterialBatch).count() == 0


def test_bulk_catalog_type_and_unit_are_authoritative(setup_materials):
    db, user, item, accessory, _ = setup_materials
    actor(db, user, "ECO")
    request = payload(item, accessory)
    request.lines[1].unit = "kg"
    with pytest.raises(HTTPException) as exc:
        eco.receive_stock_bulk(db, request, user)
    assert exc.value.status_code == 400
    db.rollback()
    rows = eco.list_items(db, user, request.lines[1].kind)
    assert next(row for row in rows if row.id == accessory.id).category.value == "accessory"


def test_bulk_is_bounded_and_validates_every_roll():
    with pytest.raises(ValidationError):
        EcoMaterialBulkReceiveIn(request_key="empty", lines=[])
    row = {"kind": "fabric", "item_id": 1, "batch_no": "R", "quantity": "0.3", "piece_count": 2,
           "roll_weights_kg": ["0.1", "0.2"], "unit": "kg"}
    assert EcoMaterialBulkReceiveIn(request_key="roll", lines=[row]).lines[0].quantity == Decimal("0.3")
    with pytest.raises(ValidationError):
        EcoMaterialBulkReceiveIn(request_key="mismatch", lines=[{**row, "quantity": "0.4"}])
    with pytest.raises(ValidationError):
        EcoMaterialBulkReceiveIn(request_key="bounded", lines=[row] * 101)

"""Isolated business-ledger regression tests; no production data is used."""
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy.exc import IntegrityError

from app.libs.dto.inventory.eco_inventory_input import EcoMaterialConsumeIn, EcoMaterialReceiveIn, FactoryFabricDispatchIn, FactoryFabricReceiptIn
from app.models.factory_scope_service import bind_session_factory
from app.models.idempotency_service import bind_idempotency_identity
from app.models.inventory import eco_inventory_service as eco
from app.models.inventory import factory_fabric_transfers_service as transfers
from app.schemas import Item, Role, StockBatch, StockMovement, User, Warehouse
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement, FactoryFabricTransfer
from app.schemas.inventory import eco_inventory_persistence as persistence
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def setup_materials():
    db = TestSessionLocal()
    user = db.query(User).filter_by(email="admin@example.com").one()
    item = Item(sku="ECO-TRANSFER-TEST", name="=Fabric test", category="fabric", unit="kg", default_cost=0, reorder_level=0)
    accessory = Item(sku="ECO-ACCESSORY-TEST", name="Buttons", category="accessory", unit="pcs", default_cost=0, reorder_level=0)
    warehouse = Warehouse(name="Milana test fabric store", type="fabric_storage")
    db.add_all([item, accessory, warehouse])
    db.flush()
    batch = StockBatch(item_id=item.id, batch_no="T-001", quantity=Decimal("100"), unit="kg", cost_per_unit=0,
                        warehouse_id=warehouse.id, qc_status="passed")
    db.add(batch)
    db.commit()
    yield db, user, item, accessory, batch
    db.close()


def actor(db, user, factory):
    bind_session_factory(user, factory)
    bind_idempotency_identity(db, user)


def dispatch(db, user, batch, quantity="30", key="send-1"):
    actor(db, user, "MIL")
    return transfers.dispatch(db, FactoryFabricDispatchIn(request_key=key, lines=[{
        "source_batch_id": batch.id, "quantity": quantity,
    }]), user)


def receipt(db, user, record, quantity, key="receipt-1"):
    actor(db, user, "ECO")
    return transfers.receive(db, record.id, FactoryFabricReceiptIn(request_key=key, lines=[{
        "line_id": record.lines[0].id, "quantity": quantity,
    }]), user)


def test_dispatch_partial_receipt_and_retry_conserve_stock(setup_materials):
    db, user, item, _, batch = setup_materials
    record = dispatch(db, user, batch)
    assert record.status.value == "in_transit"
    assert db.get(StockBatch, batch.id).quantity == Decimal("70")
    assert db.query(EcoMaterialBatch).count() == 0
    assert dispatch(db, user, batch).id == record.id
    assert db.query(StockMovement).filter_by(reference_type="FactoryFabricTransfer").count() == 1
    partial = receipt(db, user, record, "12.5")
    assert partial.status.value == "partially_received"
    assert partial.lines[0].received_quantity == Decimal("12.5")
    assert receipt(db, user, record, "12.5").status.value == "partially_received"
    assert db.query(EcoMaterialBatch).one().quantity == Decimal("12.5")
    complete = receipt(db, user, record, "17.5", "receipt-2")
    assert complete.status.value == "received"
    assert sum(row.quantity for row in db.query(EcoMaterialBatch)) == Decimal("30")
    assert sum(row.quantity for row in db.query(EcoMaterialBatch)) + db.get(StockBatch, batch.id).quantity == Decimal("100")
    assert db.query(EcoMaterialMovement).count() == 2


def test_receipt_overclaim_or_foreign_line_has_no_stock_effect(setup_materials):
    db, user, _, _, batch = setup_materials
    record = dispatch(db, user, batch)
    with pytest.raises(HTTPException) as error:
        receipt(db, user, record, "31")
    assert error.value.status_code == 409
    db.rollback()
    assert db.query(EcoMaterialBatch).count() == 0
    actor(db, user, "ECO")
    with pytest.raises(HTTPException) as error:
        transfers.receive(db, record.id, FactoryFabricReceiptIn(request_key="foreign", lines=[{"line_id": 999999, "quantity": 1}]), user)
    assert error.value.status_code == 400
    assert db.query(EcoMaterialBatch).count() == 0


def test_changed_retry_payload_refuses_without_duplicate(setup_materials):
    db, user, _, _, batch = setup_materials
    dispatch(db, user, batch)
    with pytest.raises(HTTPException) as error:
        dispatch(db, user, batch, quantity="31")
    assert error.value.status_code == 409
    assert db.get(StockBatch, batch.id).quantity == Decimal("70")
    assert db.query(FactoryFabricTransfer).count() == 1


def test_dispatch_shortage_rolls_back_entire_transfer(setup_materials):
    db, user, _, _, batch = setup_materials
    with pytest.raises(HTTPException) as error:
        dispatch(db, user, batch, quantity="101")
    assert error.value.status_code == 409
    db.rollback()
    assert db.query(FactoryFabricTransfer).count() == 0
    assert db.get(StockBatch, batch.id).quantity == Decimal("100")


def test_factory_boundaries_even_for_admin(setup_materials):
    db, user, item, _, batch = setup_materials
    actor(db, user, "MIL")
    payload = EcoMaterialReceiveIn(request_key="r", item_id=item.id, kind="fabric", batch_no="R", quantity=2)
    with pytest.raises(HTTPException) as error:
        eco.receive_stock(db, payload, user)
    assert error.value.status_code == 403
    actor(db, user, "ECO")
    with pytest.raises(HTTPException) as error:
        transfers.dispatch(db, FactoryFabricDispatchIn(request_key="s", lines=[{"source_batch_id": batch.id, "quantity": 1}]), user)
    assert error.value.status_code == 403
    actor(db, user, "BST")
    with pytest.raises(HTTPException) as error:
        transfers.list_transfers(db, user)
    assert error.value.status_code == 403


def test_eco_receipt_consumption_retry_and_available_balance(setup_materials):
    db, user, item, _, source = setup_materials
    actor(db, user, "ECO")
    payload = EcoMaterialReceiveIn(request_key="r", item_id=item.id, kind="fabric", batch_no="E-1", quantity="20.1234")
    result = eco.receive_stock(db, payload, user)
    assert eco.receive_stock(db, payload, user).batch.id == result.batch.id
    batch = db.get(EcoMaterialBatch, result.batch.id)
    persistence.set_batch_balance(db, batch, quantity=batch.quantity, reserved_quantity=Decimal("5"))
    db.commit()
    consume = EcoMaterialConsumeIn(request_key="consume-1", batch_id=batch.id, quantity="10")
    result = eco.consume_stock(db, consume, user)
    assert result.batch.quantity == Decimal("10.1234")
    assert result.batch.available_quantity == Decimal("5.1234")
    assert eco.consume_stock(db, consume, user).movement_id == result.movement_id
    with pytest.raises(HTTPException):
        eco.consume_stock(db, EcoMaterialConsumeIn(request_key="consume-2", batch_id=batch.id, quantity="6"), user)
    assert db.get(StockBatch, source.id).quantity == Decimal("100")
    history = eco.list_history(db, user)
    assert [row.kind.value for row in history] == ["consume", "receive"]


def test_accessory_direct_consumption_is_blocked_approved_issue_uses_allocation(setup_materials):
    db, user, _, item, _ = setup_materials
    actor(db, user, "ECO")
    result = eco.receive_stock(db, EcoMaterialReceiveIn(request_key="acc", item_id=item.id, kind="accessory", batch_no="A1", quantity=100), user)
    batch = db.get(EcoMaterialBatch, result.batch.id)
    with pytest.raises(HTTPException) as error:
        eco.consume_stock(db, EcoMaterialConsumeIn(request_key="bypass", batch_id=batch.id, quantity=1), user)
    assert error.value.status_code == 409
    persistence.set_batch_balance(db, batch, quantity=batch.quantity, reserved_quantity=Decimal("40"))
    db.commit()
    movement = eco.consume_eco_batch(db, batch_id=batch.id, quantity=Decimal("15"), current=user,
                                     production_order_id=None, allocated=True, reference_type="EcoAccessoryPlan", reference_id=1)
    assert movement.kind == "issue"
    assert batch.quantity == Decimal("85")
    assert batch.reserved_quantity == Decimal("25")
    db.rollback()
    assert db.get(EcoMaterialBatch, batch.id).quantity == Decimal("100")


def test_kind_mismatch_and_decimal_precision_validation(setup_materials):
    db, user, item, _, _ = setup_materials
    actor(db, user, "ECO")
    with pytest.raises(HTTPException):
        eco.receive_stock(db, EcoMaterialReceiveIn(request_key="badkind", item_id=item.id, kind="accessory", batch_no="A", quantity=1), user)
    for value in ("NaN", "Infinity", "0", "-1", "0.00001", "10000000000"):
        with pytest.raises(ValueError):
            EcoMaterialReceiveIn(request_key="invalid", item_id=item.id, kind="fabric", batch_no="A", quantity=value)


def test_excel_contains_immutable_dispatch_and_no_formulas(setup_materials):
    db, user, _, _, batch = setup_materials
    record = dispatch(db, user, batch)
    filename, data = transfers.delivery_excel(db, record.id, user)
    assert filename == "MEC-000001.xlsx"
    sheet = load_workbook(BytesIO(data)).active
    assert sheet["A6"].value == "=Fabric test"
    assert sheet["A6"].data_type == "s"
    assert sheet["E6"].value == 30
    assert sheet["G6"].value == 30


def test_missing_permission_refuses_stock_and_dispatch(setup_materials):
    db, _, item, _, _ = setup_materials
    role = Role(name="Eco inventory denied test", permissions=[])
    db.add(role)
    db.flush()
    user = User(name="Denied", email="eco-denied@test.local", password_hash="unused", role_id=role.id, factory_code="ECO", extra_permissions=[])
    db.add(user)
    db.commit()
    actor(db, user, "ECO")
    with pytest.raises(HTTPException) as error:
        eco.receive_stock(db, EcoMaterialReceiveIn(request_key="denied", item_id=item.id, kind="fabric", batch_no="X", quantity=1), user)
    assert error.value.status_code == 403


def test_database_prevents_overallocated_or_negative_eco_balance(setup_materials):
    db, user, item, _, _ = setup_materials
    actor(db, user, "ECO")
    result = eco.receive_stock(db, EcoMaterialReceiveIn(request_key="db", item_id=item.id, kind="fabric", batch_no="D", quantity=2), user)
    batch = db.get(EcoMaterialBatch, result.batch.id)
    persistence.set_batch_balance(db, batch, quantity=Decimal("2"), reserved_quantity=Decimal("3"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.get(EcoMaterialBatch, batch.id).reserved_quantity == 0

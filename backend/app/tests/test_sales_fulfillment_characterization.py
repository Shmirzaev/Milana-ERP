"""Existing Sales allocation behavior required by the proposed Fulfillment seam.

These tests exercise the current caller, not an unapproved future interface.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.db.session import SessionLocal
from app.libs.dto.sales.sales_order_input import SalesOrderItemIn
from app.models.sales.ready_stock_service import _reserve_branded_stock
from app.models.fulfillment.stock_service import _select_whole_packages
from app.schemas import (
    FinishedGoodsStock, LegacyStockReceipt, Model, Package, ProductionOrder,
    SalesOrder, SalesOrderItem, StockReservation, User,
)
from app.tests.test_sales_ready_packs import _packs, _payload


def test_piece_allocation_mixes_whole_package_and_legacy_remainder_and_keeps_display_identity():
    with SessionLocal() as db:
        suffix = uuid4().hex[:10]
        model = Model(code=f"SEAM-{suffix}", name="Seam characterization", status="approved")
        db.add(model)
        db.flush()
        production = ProductionOrder(production_no=f"SEAM-PO-{suffix}", model_id=model.id,
                                     production_type="branded_stock", planned_quantity=6, status="completed")
        legacy = LegacyStockReceipt(source_system="TEST", source_warehouse_id="test",
                                    source_record_id=suffix, source_checksum="0" * 64, source_payload={})
        order = SalesOrder(order_no=f"SEAM-SO-{suffix}", order_type="branded_stock_sale", status="draft")
        db.add_all([production, legacy, order])
        db.flush()
        whole = Package(package_no=f"SEAM-W-{suffix}", barcode=f"SEAM-W-{suffix}",
                        production_order_id=production.id, model_id=model.id, color="white",
                        total_quantity=6, capacity=6, status="received_in_storage")
        partial = Package(package_no=f"SEAM-L-{suffix}", barcode=f"SEAM-L-{suffix}",
                          legacy_receipt_id=legacy.id, model_id=model.id, color="white",
                          total_quantity=5, capacity=5, status="received_in_storage")
        db.add_all([whole, partial])
        db.flush()
        stocks = [FinishedGoodsStock(package_id=p.id, model_id=model.id, color="white", size="M",
                                    quantity=q, available_qty=q, reserved_qty=0, sold_qty=0, status="available")
                  for p, q in [(whole, 6), (partial, 5)]]
        line = SalesOrderItem(sales_order_id=order.id, model_id=model.id, color="white", size="M",
                              quantity=8, unit_price=2, source_type="from_stock")
        db.add_all([*stocks, line])
        db.flush()
        actor = db.query(User).order_by(User.id).first()
        reservations, shortages = _reserve_branded_stock(db, so=order, current=actor, lines=[line],
                                                         notify_shortage=False, fail_on_shortage=True)
        assert shortages == []
        assert reservations == [
            {"stock_id": stocks[0].id, "package_id": whole.id, "qty": 6},
            {"stock_id": stocks[1].id, "package_id": None, "qty": 2},
        ]
        assert (stocks[0].available_qty, stocks[0].reserved_qty, stocks[0].status) == (0, 6, "reserved")
        assert (stocks[1].available_qty, stocks[1].reserved_qty, stocks[1].status) == (3, 2, "available")
        db.flush()
        persisted = db.query(StockReservation).filter(StockReservation.sales_order_id == order.id).order_by(StockReservation.id).all()
        assert [(r.package_id, r.quantity) for r in persisted] == [(whole.id, 6), (partial.id, 2)]
        with pytest.raises(HTTPException, match="already been fully reserved"):
            _reserve_branded_stock(db, so=order, current=actor, lines=[line], notify_shortage=False)
        db.rollback()
        assert db.query(StockReservation).filter(StockReservation.sales_order_id == order.id).count() == 0


def test_selection_order_is_predecessor_reconstruction_not_ascending_package_id():
    groups = {10: (SimpleNamespace(total_quantity=6), []), 20: (SimpleNamespace(total_quantity=4), [])}
    assert _select_whole_packages(groups, 10) == [20, 10]
    assert _select_whole_packages(groups, 6) == [10]


def test_piece_zero_remains_valid_input_but_all_zero_reservation_is_existing_409(client, auth_headers):
    assert SalesOrderItemIn(model_id=1, color="white", size="M", quantity=0).quantity == 0
    model_id, _ = _packs((6,))
    response = client.post("/api/sales-orders", headers=auth_headers, json={
        "order_type": "branded_stock_sale", "items": [{"model_id": model_id, "color": "white", "size": "46", "quantity": 0}],
    })
    assert response.status_code == 409, response.text
    assert "already been fully reserved" in response.json()["detail"]


def test_first_grade_pack_request_remains_forbidden(client, auth_headers):
    model_id, _ = _packs((6,))
    response = client.post("/api/sales-orders", headers=auth_headers,
                           json=_payload(model_id, source_type="first_grade"))
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "FIRST_GRADE_SEPARATE_ORDER"


def test_pack_results_preserve_each_sales_line_quantity_and_total(client, auth_headers):
    first_model, _ = _packs((6,))
    second_model, _ = _packs((5,))
    payload = _payload(first_model)
    payload["items"].extend(_payload(second_model)["items"])
    response = client.post("/api/sales-orders", headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    assert {r["model_id"]: r["quantity"] for r in response.json()["items"]} == {first_model: 6, second_model: 5}
    assert response.json()["total_amount"] == 22


def test_existing_piece_lock_flags_mean_no_key_update_and_pack_lock_stays_full():
    with SessionLocal() as db:
        piece = str(db.query(Package).order_by(Package.id).with_for_update(key_share=True, of=Package).statement.compile(dialect=postgresql.dialect()))
        pack = str(db.query(Package).order_by(Package.id).with_for_update(of=Package).statement.compile(dialect=postgresql.dialect()))
    assert piece.endswith("FOR NO KEY UPDATE OF packages")
    assert pack.endswith("FOR UPDATE OF packages")

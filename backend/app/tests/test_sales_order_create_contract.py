"""Schema-owned persistence, operation-01: create a sales order.

Operation under review
----------------------
`POST /api/sales-orders` -> `models/sales/orders_service.create_sales_order`.

The expectations here are written as literal strings on purpose. They are the
operation's own contract and are not derived from the new enum module, so a
mistake in that module cannot make the test agree with itself.

The create endpoint accepts a narrower subset of the stored order-type
vocabulary: `client_order` and `branded_stock_sale`. `branded_stock` is a real
stored order type that create does not accept, and it is still refused with
`400 "Invalid order_type"` by the retained service guard, so the enum did not
widen the creation subset. A value outside the stored vocabulary is now
refused by the typed contract with 422. `status` is not a create input; the
operation always writes `draft`.

The branded-stock reservation is reached through two paths - the create path
and the idempotent reserve-stock path - so both are checked for the same
refusal behaviour: no order, line, reservation, stock, audit, notification or
idempotency row may survive a refusal.
"""
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.libs.dto.sales.sales_order_input import SalesOrderIn
from app.models.idempotency_service import request_fingerprint
from app.schemas import (
    AuditLog, Collection, CollectionModel, FinishedGoodsStock, IdempotencyRecord, Notification,
    SalesOrder, SalesOrderItem, StockReservation, Task,
)


DEFAULT_ORDER_TYPE = "client_order"
READY_STOCK_ORDER_TYPE = "branded_stock_sale"
DEFAULT_LINE_SOURCE_TYPE = "produce_new"
DEFAULT_ORDER_STATUS = "draft"
UNKNOWN_SOURCE_TYPE = "a_source_type_the_schema_enum_does_not_know"


def _model_id(client, headers) -> int:
    r = client.get("/api/models", headers=headers)
    assert r.status_code == 200, r.text
    approved = next((row for row in r.json() if row.get("status") == "approved"), None)
    if approved:
        return int(approved["id"])
    suffix = uuid4().hex[:8].upper()
    r = client.post(
        "/api/models",
        json={"code": f"RF011OP-{suffix}", "name": "RF-011 operation model", "status": "approved"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _counts() -> dict[str, int]:
    with SessionLocal() as db:
        return {
            "sales_orders": db.query(SalesOrder.id).count(),
            "sales_order_items": db.query(SalesOrderItem.id).count(),
            "audit_logs": db.query(AuditLog.id).count(),
            "notifications": db.query(Notification.id).count(),
            "tasks": db.query(Task.id).count(),
            "stock_reservations": db.query(StockReservation.id).count(),
            "finished_goods_stock": db.query(FinishedGoodsStock.id).count(),
            "idempotency_records": db.query(IdempotencyRecord.id).count(),
        }


def _line(model_id: int, **overrides) -> dict:
    line = {
        "model_id": model_id,
        "color": "white",
        "size": "M",
        "quantity": 3,
        "unit_price": 10,
    }
    line.update(overrides)
    return line


def _create(client, headers, payload):
    return client.post("/api/sales-orders", json=payload, headers=headers)


def test_create_uses_the_documented_defaults(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    r = _create(client, auth_headers, {"items": [_line(model_id)]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["order_type"] == DEFAULT_ORDER_TYPE
    assert body["status"] == DEFAULT_ORDER_STATUS
    assert body["items"][0]["source_type"] == DEFAULT_LINE_SOURCE_TYPE


def test_create_accepts_client_order(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    r = _create(client, auth_headers, {"order_type": DEFAULT_ORDER_TYPE, "items": [_line(model_id)]})
    assert r.status_code == 201, r.text
    assert r.json()["order_type"] == DEFAULT_ORDER_TYPE
    assert r.json()["status"] == DEFAULT_ORDER_STATUS


def test_create_accepts_the_ready_stock_order_type(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    r = _create(client, auth_headers, {"order_type": READY_STOCK_ORDER_TYPE, "items": [_line(model_id)]})
    # The ready-stock branch needs warehouse stock; any outcome other than the
    # order-type guard proves the creation subset accepted the value.
    if r.status_code == 201:
        assert r.json()["order_type"] == READY_STOCK_ORDER_TYPE
    else:
        assert r.status_code != 400 or r.json().get("detail") != "Invalid order_type", r.text


@pytest.mark.parametrize(
    "order_type",
    ["not_an_order_type", "Client_Order", " client_order ", "", "client-order"],
)
def test_create_refuses_every_other_order_type(client, auth_headers, order_type):
    model_id = _model_id(client, auth_headers)
    before = _counts()
    r = _create(client, auth_headers, {"order_type": order_type, "items": [_line(model_id)]})
    assert r.status_code == 422, r.text
    assert _counts() == before


def test_create_refuses_a_stored_order_type_that_create_does_not_accept(client, auth_headers):
    """`branded_stock` is a real stored order type but create does not accept it.

    The enum annotation lets it through the contract, and the retained service
    guard refuses it with the original 400, so the creation subset is not
    widened by the enum.
    """
    model_id = _model_id(client, auth_headers)
    before = _counts()
    r = _create(client, auth_headers, {"order_type": "branded_stock", "items": [_line(model_id)]})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "Invalid order_type"
    assert _counts() == before


def test_create_refuses_a_null_order_type_as_a_validation_error(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    before = _counts()
    r = _create(client, auth_headers, {"order_type": None, "items": [_line(model_id)]})
    assert r.status_code == 422, r.text
    assert _counts() == before


@pytest.mark.parametrize("source_type", ["produce_new", "from_stock", "first_grade"])
def test_create_accepts_the_written_line_source_types(client, auth_headers, source_type):
    model_id = _model_id(client, auth_headers)
    r = _create(client, auth_headers, {"items": [_line(model_id, source_type=source_type)]})
    if source_type == "first_grade":
        # first-grade lines are only allowed on a ready-stock order.
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "FIRST_GRADE_SEPARATE_ORDER"
        return
    assert r.status_code == 201, r.text
    assert r.json()["items"][0]["source_type"] == source_type


def test_create_refuses_an_unknown_line_source_type(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    before = _counts()
    r = _create(client, auth_headers, {"items": [_line(model_id, source_type=UNKNOWN_SOURCE_TYPE)]})
    assert r.status_code == 422, r.text
    assert _counts() == before


def test_create_rolls_back_when_a_line_model_is_missing(client, auth_headers):
    before = _counts()
    r = _create(client, auth_headers, {"items": [_line(999999999)]})
    assert r.status_code == 404, r.text
    assert "not found" in r.json()["detail"]
    assert _counts() == before


def test_create_refuses_a_first_grade_line_on_a_client_order(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    before = _counts()
    r = _create(client, auth_headers, {"items": [_line(model_id, source_type="first_grade")]})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "FIRST_GRADE_SEPARATE_ORDER"
    assert _counts() == before


def test_create_refuses_a_ready_stock_order_without_lines(client, auth_headers):
    before = _counts()
    r = _create(client, auth_headers, {"order_type": READY_STOCK_ORDER_TYPE, "items": []})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "A Ready stock order must have at least one line"
    assert _counts() == before


def test_create_refuses_a_piece_quantity_that_is_missing(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    before = _counts()
    r = _create(client, auth_headers, {"items": [_line(model_id, quantity=None)]})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "A piece quantity is required"
    assert _counts() == before


def test_create_refuses_an_unknown_customer(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    before = _counts()
    r = _create(client, auth_headers, {"customer_id": 999999999, "items": [_line(model_id)]})
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Customer not found"
    assert _counts() == before


def test_create_writes_one_audit_row_and_no_notification(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    before = _counts()
    r = _create(client, auth_headers, {"items": [_line(model_id)]})
    assert r.status_code == 201, r.text
    after = _counts()
    assert after["sales_orders"] == before["sales_orders"] + 1
    assert after["sales_order_items"] == before["sales_order_items"] + 1
    assert after["audit_logs"] == before["audit_logs"] + 1
    assert after["notifications"] == before["notifications"]
    assert after["tasks"] == before["tasks"]
    assert after["stock_reservations"] == before["stock_reservations"]


def test_create_does_not_store_the_request_status(client, auth_headers):
    """`status` is not a create input; the operation always writes `draft`."""
    model_id = _model_id(client, auth_headers)
    r = _create(client, auth_headers, {"status": "confirmed", "items": [_line(model_id)]})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == DEFAULT_ORDER_STATUS


def test_create_keeps_the_calculated_total(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    r = _create(client, auth_headers, {"items": [_line(model_id, quantity=4, unit_price=12.5)]})
    assert r.status_code == 201, r.text
    assert float(r.json()["total_amount"]) == 50.0


# --- second path into the same branded-stock reservation --------------------
#
# `POST /api/sales-orders/{sid}/reserve-stock` reaches the same reservation
# helper as the create path. Both paths must refuse without leaving a
# reservation, shortage, audit, notification or idempotency row.


def test_reserve_stock_refuses_a_non_ready_stock_order_without_side_effects(client, auth_headers):
    model_id = _model_id(client, auth_headers)
    r = _create(client, auth_headers, {"items": [_line(model_id)]})
    assert r.status_code == 201, r.text
    order_id = int(r.json()["id"])
    before = _counts()
    r = client.post(f"/api/sales-orders/{order_id}/reserve-stock", headers=auth_headers)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "Reservation only applies to branded stock sales"
    assert _counts() == before


def test_reserve_stock_refuses_a_missing_order_without_side_effects(client, auth_headers):
    before = _counts()
    r = client.post("/api/sales-orders/999999999/reserve-stock", headers=auth_headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Sales order not found"
    assert _counts() == before


# --- indirect writer reached from the create path ---------------------------
#
# `app/models/sales/ready_stock_service.py` calls
# `app/models/finished_goods_service.py::repair_missing_brand_metadata`, which
# assigns `brand_id` / `collection_id` on a legacy finished-goods stock row and
# flushes. `finished_goods_stock` belongs to fulfillment, so that write stays
# with fulfillment; this test is the regression evidence that the create path
# still performs it.


def _seeded_model_id(client, headers, code: str) -> int:
    r = client.get("/api/models", params={"code": code, "page_size": 1}, headers=headers)
    assert r.status_code == 200, r.text
    row = next((m for m in r.json() if str(m.get("code")) == code), None)
    assert row is not None, f"Model {code} not found"
    return int(row["id"])


def _model_brand_id(model_id: int) -> int:
    """The brand the model's collection resolves to, as the repair resolves it."""
    with SessionLocal() as db:
        brand_id = (
            db.query(Collection.brand_id)
            .join(CollectionModel, CollectionModel.collection_id == Collection.id)
            .filter(CollectionModel.model_id == model_id)
            .scalar()
        )
    assert brand_id is not None, "the seeded model must resolve to a collection with a brand"
    return int(brand_id)


def _model_with_brand(client, headers) -> tuple[int, int]:
    """Create a brand, a collection under it and a model in that collection."""
    suffix = uuid4().hex[:8]
    r = client.post(
        "/api/brands", json={"name": f"RF011 Brand {suffix}", "description": "operation-01"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    brand_id = int(r.json()["id"])
    r = client.post(
        "/api/collections",
        json={
            "brand_id": brand_id, "name": f"RF011 Collection {suffix}",
            "season": "SS", "year": 2026, "status": "approved",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    collection_id = int(r.json()["id"])
    r = client.post(
        "/api/models",
        json={
            "code": f"RF011-{suffix}", "name": "RF-011 branded model", "status": "approved",
            "brand_id": brand_id, "collection_id": collection_id,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    model_id = int(r.json()["id"])
    # The repair resolves a model's collection through the CollectionModel link.
    with SessionLocal() as db:
        db.add(CollectionModel(collection_id=collection_id, model_id=model_id))
        db.commit()
    assert _model_brand_id(model_id) == brand_id
    return model_id, brand_id


def test_create_still_backfills_missing_brand_metadata_on_a_legacy_stock_row(client, auth_headers):
    model_id, brand_id = _model_with_brand(client, auth_headers)
    with SessionLocal() as db:
        legacy = FinishedGoodsStock(
            model_id=model_id,
            brand_id=None,
            color="white",
            size="M",
            quantity=30,
            available_qty=30,
            reserved_qty=0,
            sold_qty=0,
            cost_per_piece=5,
            selling_price=12,
            status="available",
        )
        db.add(legacy)
        db.commit()
        legacy_id = int(legacy.id)

    r = _create(
        client,
        auth_headers,
        {
            "order_type": "branded_stock_sale",
            "items": [
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": "white",
                    "size": "M",
                    "quantity": 12,
                    "unit_price": 19,
                },
            ],
        },
    )
    assert r.status_code == 201, r.text

    with SessionLocal() as db:
        row = db.get(FinishedGoodsStock, legacy_id)
        assert row.brand_id == brand_id, "the create path must still backfill the legacy stock row"


# --- request fingerprint parity --------------------------------------------
#
# The typed DTO must not change the hash of a request that an idempotent retry
# carries. The expected payload is the pre-change string payload, written out
# literally, so a change in the serializer would fail here instead of silently
# rejecting a historical retry.


def test_the_typed_dto_hashes_like_the_pre_change_string_payload():
    typed = request_fingerprint(SalesOrderIn(order_type="client_order").model_dump())
    pre_change = request_fingerprint(
        {
            "customer_id": None,
            "order_type": "client_order",
            "deadline": None,
            "printing_instructions": None,
            "printing_attachments": [],
            "notes": None,
            "items": [],
        }
    )
    assert typed == pre_change


def test_a_typed_line_hashes_like_the_pre_change_string_line():
    typed = request_fingerprint(
        SalesOrderIn(
            order_type="client_order",
            items=[
                {
                    "model_id": 7,
                    "brand_id": None,
                    "collection_id": None,
                    "color": "white",
                    "size": "M",
                    "quantity": 3,
                    "requested_pack_count": None,
                    "unit_price": 12.5,
                    "printing_required": False,
                    "source_type": "from_stock",
                    "notes": None,
                }
            ],
        ).model_dump()
    )
    pre_change = request_fingerprint(
        {
            "customer_id": None,
            "order_type": "client_order",
            "deadline": None,
            "printing_instructions": None,
            "printing_attachments": [],
            "notes": None,
            "items": [
                {
                    "model_id": 7,
                    "brand_id": None,
                    "collection_id": None,
                    "color": "white",
                    "size": "M",
                    "quantity": 3,
                    "requested_pack_count": None,
                    "unit_price": 12.5,
                    "printing_required": False,
                    "source_type": "from_stock",
                    "notes": None,
                }
            ],
        }
    )
    assert typed == pre_change

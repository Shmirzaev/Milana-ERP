"""Sales-order line prices must match the cents stored by NUMERIC columns."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    FinishedGoodsStock,
    ManualPackageReceipt,
    Model,
    Package,
    PackageItem,
    SalesOrder,
    SalesOrderItem,
    StockReservation,
    User,
)
from app.schemas.sales import SalesOrderItemIn


MAX_ITEM_PRICE = Decimal("9999999999.99")


def _model(*, selling_price: Decimal | str | None = None) -> int:
    with SessionLocal() as db:
        model = Model(
            code=f"LINE-PRICE-{uuid4().hex[:12]}",
            name="Sales order line price precision",
            status="approved",
            catalog_scope="standard",
            selling_price=selling_price,
        )
        db.add(model)
        db.commit()
        return int(model.id)


def _payload(model_id: int, *, unit_price: str | None = None, quantity: int = 1) -> dict:
    line = {
        "model_id": model_id,
        "color": "black",
        "size": "M",
        "quantity": quantity,
    }
    if unit_price is not None:
        line["unit_price"] = unit_price
    return {"order_type": "client_order", "items": [line]}


def _write_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(SalesOrder).count(),
            db.query(SalesOrderItem).count(),
            db.query(AuditLog).count(),
        )


def _received_pack(model_id: int, quantity: int) -> tuple[int, int]:
    with SessionLocal() as db:
        user_id = int(db.query(User.id).filter_by(email="admin@example.com").scalar())
        marker = uuid4().hex[:12]
        receipt = ManualPackageReceipt(
            receipt_no=f"PRICE-RECEIPT-{marker}",
            created_by=user_id,
            evidence={},
            evidence_hash="a" * 64,
        )
        db.add(receipt)
        db.flush()
        package = Package(
            package_no=f"PRICE-PACK-{marker}",
            barcode=f"PRICE-BARCODE-{marker}",
            manual_receipt_id=receipt.id,
            model_id=model_id,
            color="black",
            total_quantity=quantity,
            capacity=quantity,
            status="received_in_storage",
            packaging_department_code="PKG",
            packed_by=user_id,
            received_by=user_id,
            received_at=datetime.now(timezone.utc),
        )
        db.add(package)
        db.flush()
        stock = FinishedGoodsStock(
            package_id=package.id,
            model_id=model_id,
            color="black",
            size="M",
            quantity=quantity,
            available_qty=quantity,
            status="available",
        )
        db.add_all([
            PackageItem(package_id=package.id, model_id=model_id, color="black", size="M", quantity=quantity),
            stock,
        ])
        db.commit()
        return int(package.id), int(stock.id)


def test_sales_order_item_schema_preserves_decimal_and_explicit_zero():
    maximum = SalesOrderItemIn(
        model_id=1,
        color="black",
        size="M",
        quantity=1,
        unit_price=str(MAX_ITEM_PRICE),
    )
    zero = SalesOrderItemIn(model_id=1, color="black", size="M", quantity=1, unit_price="0.00")

    assert maximum.unit_price == MAX_ITEM_PRICE
    assert zero.unit_price == Decimal("0.00")
    assert SalesOrderItemIn(model_id=1, color="black", size="M", quantity=1).unit_price is None


@pytest.mark.parametrize("unit_price", ["0.994", "1.001", "1.00000000000000001"])
def test_sales_order_rejects_subcent_explicit_price_without_writes(client, auth_headers, unit_price):
    model_id = _model()
    before = _write_counts()

    response = client.post("/api/sales-orders", headers=auth_headers, json=_payload(model_id, unit_price=unit_price))

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_sales_order_persists_exact_maximum_explicit_unit_price(client, auth_headers):
    model_id = _model()

    response = client.post(
        "/api/sales-orders", headers=auth_headers, json=_payload(model_id, unit_price=str(MAX_ITEM_PRICE))
    )

    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    with SessionLocal() as db:
        line = db.query(SalesOrderItem).filter_by(sales_order_id=order_id).one()
        order = db.get(SalesOrder, order_id)
        assert line.unit_price == MAX_ITEM_PRICE
        assert order.total_amount == MAX_ITEM_PRICE


def test_sales_order_explicit_zero_overrides_catalog_price(client, auth_headers):
    model_id = _model(selling_price="12.3456")

    response = client.post("/api/sales-orders", headers=auth_headers, json=_payload(model_id, unit_price="0.00"))

    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    with SessionLocal() as db:
        line = db.query(SalesOrderItem).filter_by(sales_order_id=order_id).one()
        assert line.unit_price == Decimal("0.00")
        assert db.get(SalesOrder, order_id).total_amount == Decimal("0.00")


def test_sales_order_accepts_trailing_zero_explicit_cents(client, auth_headers):
    model_id = _model()

    response = client.post("/api/sales-orders", headers=auth_headers, json=_payload(model_id, unit_price="0.9900"))

    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    with SessionLocal() as db:
        line = db.query(SalesOrderItem).filter_by(sales_order_id=order_id).one()
        assert line.unit_price == Decimal("0.99")
        assert db.get(SalesOrder, order_id).total_amount == Decimal("0.99")


def test_sales_order_rounds_omitted_catalog_price_before_line_and_total(client, auth_headers):
    model_id = _model(selling_price="1.0050")

    response = client.post("/api/sales-orders", headers=auth_headers, json=_payload(model_id, quantity=2))

    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    with SessionLocal() as db:
        line = db.query(SalesOrderItem).filter_by(sales_order_id=order_id).one()
        assert line.unit_price == Decimal("1.01")
        assert db.get(SalesOrder, order_id).total_amount == Decimal("2.02")


def test_sales_order_rejects_unrepresentable_omitted_catalog_price_before_writes(client, auth_headers):
    model_id = _model(selling_price="10000000000.0000")
    before = _write_counts()

    response = client.post("/api/sales-orders", headers=auth_headers, json=_payload(model_id))

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_sales_order_rejects_catalog_rounding_overflow_before_writes(client, auth_headers):
    model_id = _model(selling_price="9999999999.9950")
    before = _write_counts()

    response = client.post("/api/sales-orders", headers=auth_headers, json=_payload(model_id))

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_pack_order_rechecks_total_after_package_quantities_are_allocated(client, auth_headers):
    model_id = _model()
    package_id, stock_id = _received_pack(model_id, 101)
    before = _write_counts()
    response = client.post(
        "/api/sales-orders",
        headers=auth_headers,
        json={
            "order_type": "branded_stock_sale",
            "items": [{
                "model_id": model_id,
                "color": "mixed",
                "size": "any",
                "requested_pack_count": 1,
                "unit_price": str(MAX_ITEM_PRICE),
                "source_type": "from_stock",
            }],
        },
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before
    with SessionLocal() as db:
        stock = db.get(FinishedGoodsStock, stock_id)
        assert stock.package_id == package_id
        assert stock.available_qty == 101
        assert stock.reserved_qty == 0
        assert db.query(StockReservation).filter_by(package_id=package_id).count() == 0

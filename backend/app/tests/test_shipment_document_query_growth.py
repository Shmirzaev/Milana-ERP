from types import SimpleNamespace

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    LegacyStockReceipt, ManualPackageReceipt, Model, Package, PackageItem,
    SalesOrder, SalesOrderItem, Shipment, ShipmentPackage, User,
)
from app.services.shipment_invoice import build_invoice_rows
from app.services.shipment_review import _shipment_document_indexes, shipment_document


class CountingIterable:
    def __init__(self, values):
        self.values = values
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return iter(self.values)


def test_document_indexes_read_each_input_once():
    contents = CountingIterable([
        SimpleNamespace(id=index, package_id=index % 7, model_id=index % 3)
        for index in range(100)
    ])
    order_items = CountingIterable([
        SimpleNamespace(model_id=index % 3, color="mixed", size="any", unit_price=index % 5)
        for index in range(80)
    ])

    by_package, exact_prices, wildcard_prices = _shipment_document_indexes(contents, order_items)

    assert contents.iterations == order_items.iterations == 1
    assert sum(map(len, by_package.values())) == 100
    assert len(exact_prices) == 3
    assert len(wildcard_prices) == 3


def test_invoice_rows_index_lines_once_and_preserve_package_order_and_empty_groups():
    lines = CountingIterable([
        {"package_no": "P2", "model_code": "M-2", "quantity": 2, "size": "L", "color": "red", "unit_price": "3", "amount": "6"},
        {"package_no": "P1", "model_code": "M-1", "quantity": 1, "size": "S", "color": "navy", "unit_price": "2", "amount": "2"},
        {"package_no": "P1", "model_code": "M-1", "quantity": 3, "size": "M", "color": "navy", "unit_price": "2", "amount": "6"},
    ])
    packages = CountingIterable([
        {"package_no": "P1", "quantity": 4, "weight_kg": "1.5"},
        {"package_no": "EMPTY", "quantity": 7, "weight_kg": None},
        {"package_no": "P2", "quantity": 2, "weight_kg": "2.0"},
    ])

    rows = build_invoice_rows(lines, packages)

    assert lines.iterations == packages.iterations == 1
    assert [row["package_no"] for row in rows] == ["P1", "EMPTY", "P2"]
    assert [(row["quantity"], row["amount"]) for row in rows] == [(4, "8.00"), (7, None), (2, "6.00")]
    assert [item["size"] for item in rows[0]["sizes"]] == ["S", "M"]


def _create_manual_shipment(db, suffix, package_count):
    user_id = db.query(User.id).order_by(User.id).first()[0]
    model = Model(code=f"PERF34-{suffix}", name="PERF34 manual", status="approved", selling_price=2.5)
    shipment = Shipment(shipment_no=f"PERF34-SH-{suffix}", status="created", dispatch_snapshot={"manual": True})
    db.add_all([model, shipment])
    db.flush()
    for number in range(package_count):
        receipt = ManualPackageReceipt(
            receipt_no=f"PERF34-R-{suffix}-{number}", created_by=user_id,
            evidence={"configured_sizes": ["S", "M", "S"]}, evidence_hash="a" * 64,
        )
        db.add(receipt)
        db.flush()
        package = Package(
            package_no=f"PERF34-P-{suffix}-{number}", barcode=f"PERF34-B-{suffix}-{number}",
            model_id=model.id, color="navy", total_quantity=1, capacity=1,
            manual_receipt_id=receipt.id, status="received_in_storage",
        )
        db.add(package)
        db.flush()
        db.add_all([
            PackageItem(package_id=package.id, model_id=model.id, color="navy", size="mixed", quantity=1),
            ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=1),
        ])
    db.commit()
    return shipment.id


def _document_select_count(shipment_id):
    with SessionLocal() as db:
        shipment = db.get(Shipment, shipment_id)
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            document = shipment_document(db, shipment)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return document, len(statements)


def test_manual_document_query_count_is_constant_as_packages_grow():
    with SessionLocal() as db:
        one_id = _create_manual_shipment(db, "ONE", 1)
        many_id = _create_manual_shipment(db, "MANY", 20)

    one, one_selects = _document_select_count(one_id)
    many, many_selects = _document_select_count(many_id)

    assert (one_selects, many_selects) == (4, 4)
    assert one["lines"][0]["size_display"] == "S, M"
    assert len(many["lines"]) == many["packages_count"] == 20


def test_price_precedence_ambiguity_order_and_frozen_document_are_preserved():
    with SessionLocal() as db:
        exact_model = Model(code="PERF34-EXACT", name="Exact", status="approved")
        ambiguous_model = Model(code="PERF34-AMB", name="Ambiguous", status="approved")
        order = SalesOrder(order_no="PERF34-ORDER", status="reserved", total_amount=0)
        db.add_all([exact_model, ambiguous_model, order])
        db.flush()
        db.add_all([
            SalesOrderItem(sales_order_id=order.id, model_id=exact_model.id, color="mixed", size="any", quantity=2, unit_price=10),
            SalesOrderItem(sales_order_id=order.id, model_id=exact_model.id, color="navy", size="M", quantity=1, unit_price=20),
            SalesOrderItem(sales_order_id=order.id, model_id=ambiguous_model.id, color="mixed", size="any", quantity=1, unit_price=5),
            SalesOrderItem(sales_order_id=order.id, model_id=ambiguous_model.id, color="*", size="bag", quantity=1, unit_price=6),
        ])
        shipment = Shipment(shipment_no="PERF34-ORDER-SH", sales_order_id=order.id, status="created")
        db.add(shipment)
        db.flush()
        variants = [
            (exact_model, "navy", "M", "PERF34-P-EXACT"),
            (exact_model, "red", "L", "PERF34-P-WILD"),
            (ambiguous_model, "black", "XL", "PERF34-P-AMB"),
        ]
        for number, (model, color, size, package_no) in enumerate(variants):
            receipt = LegacyStockReceipt(
                source_system="TEST", source_warehouse_id="PERF34",
                source_record_id=str(number), source_checksum=str(number + 1) * 64,
                source_payload={"quantity": 1},
            )
            db.add(receipt)
            db.flush()
            package = Package(
                package_no=package_no, barcode=f"{package_no}-B", model_id=model.id,
                color=color, total_quantity=1, capacity=1, legacy_receipt_id=receipt.id,
                status="reserved",
            )
            db.add(package)
            db.flush()
            db.add_all([
                PackageItem(package_id=package.id, model_id=model.id, color=color, size=size, quantity=1),
                ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=1),
            ])
        db.commit()

        document = shipment_document(db, shipment)
        assert [line["package_no"] for line in document["lines"]] == [value[3] for value in variants]
        assert [line["unit_price"] for line in document["lines"]] == ["20.00", "10.00", None]
        assert document["pricing_complete"] is False
        assert document["amount"] is None
        assert document["basis"] == "148706ed005a24e78430a46bc5c54fbea4306ba6fd86a75fb58d648d76df678a"

        shipment.status = "shipped"
        shipment.dispatch_snapshot = {"document": document}
        db.query(SalesOrderItem).filter_by(sales_order_id=order.id).update({"unit_price": 999})
        db.flush()
        assert shipment_document(db, shipment) == document

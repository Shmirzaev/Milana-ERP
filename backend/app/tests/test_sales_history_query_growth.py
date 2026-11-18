"""Measure SQL growth for selected mixed sales/stock history rows on PostgreSQL."""

import pytest
from sqlalchemy import event

from app.models.sales import history_service
from app.tests.test_sales_history_candidate_loading import (
    _seed,
    pg as pg,
    sales_history_postgres_sessions as sales_history_postgres_sessions,
)


@pytest.mark.parametrize("distinct", [False, True])
def test_mixed_history_summary_query_growth(pg, distinct):
    from uuid import uuid4
    from app.schemas import Customer, CuttingRecord, Department, Model, Package, ProductionOrder, SalesOrder, SalesOrderItem, WorkOrder

    engine, session_factory = pg
    case = _seed(session_factory, rows=[(i, "draft", "client_order", "draft") for i in range(50)])
    suffix = uuid4().hex[:8]
    with session_factory.begin() as db:
        dep = Department(name=f"Growth {suffix}", code=f"G{suffix}")
        db.add(dep)
        db.flush()
        for index, (sales_id, po_id) in enumerate(zip(case["sales_ids"], case["production_ids"])):
            so = db.get(SalesOrder, sales_id)
            po = db.get(ProductionOrder, po_id)
            if distinct:
                customer = Customer(name=f"Growth customer {suffix}-{index}")
                model = Model(code=f"G-{suffix}-{index}", name="Growth model", status="approved")
                db.add_all([customer, model])
                db.flush()
                so.customer_id = customer.id
                po.model_id = model.id
            if index or distinct:
                db.add(SalesOrderItem(sales_order_id=so.id, model_id=po.model_id, quantity=1, color="white", size="M"))
            wo = WorkOrder(production_order_id=po.id, department_id=dep.id, operation="cutting")
            db.add(wo)
            db.flush()
            db.add_all([
                CuttingRecord(work_order_id=wo.id, cut_pieces=1),
                Package(package_no=f"G-PKG-{suffix}-{index}", barcode=f"G-BC-{suffix}-{index}", production_order_id=po.id, model_id=po.model_id, color="white", total_quantity=1, capacity=10),
            ])
    counts = []
    for size in (1, 10, 50):
        statements = []

        def record(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            with session_factory() as db:
                rows = history_service.list_sales_order_history(db, page_size=size)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert len(rows) == size
        counts.append(len(statements))
    # A page can need additional fixed queries when it first contains both kinds.
    # Further growth with both kinds present should not add a query per row.
    assert counts[1] <= counts[0] + 20, f"SELECT counts at 1/10/50: {counts}"
    assert counts[2] <= counts[1] + 2, f"SELECT counts at 1/10/50: {counts}"


def test_rich_summary_matches_direct_builders_and_fixed_values(pg):
    from uuid import uuid4
    from app.schemas import (
        CuttingRecord, Department, Invoice, Item, Package, PackagingRecord, Payment,
        PrintingRecord, ProductionOrder, SalesOrder, SewingRecord, Shipment,
        ShipmentPackage, StockMovement, WorkOrder,
    )

    _, sessions = pg
    case = _seed(sessions, rows=[(1, "draft", "client_order", "draft")])
    with sessions.begin() as db:
        suffix = uuid4().hex[:8]
        dep = Department(name=f"History {suffix}", code=f"H{suffix}")
        item = Item(sku=f"H-{suffix}", name="Fabric", category="fabric", unit="kg", default_cost=2)
        db.add_all([dep, item])
        db.flush()
        so = db.get(SalesOrder, case["sales_ids"][0])
        stock = db.get(ProductionOrder, case["production_ids"][0])
        po = ProductionOrder(production_no=f"H-PO-{suffix}", production_type="client_order", sales_order_id=so.id, model_id=case["model_id"], status="draft", planned_quantity=8)
        db.add(po)
        db.flush()
        for target in (po, stock):
            wo = WorkOrder(production_order_id=target.id, department_id=dep.id, operation="cutting")
            db.add(wo)
            db.flush()
            db.add_all([
                CuttingRecord(work_order_id=wo.id, cut_pieces=7, passed_pieces=6),
                PrintingRecord(work_order_id=wo.id, printed_qty=5),
                SewingRecord(work_order_id=wo.id, sewn_qty=4, passed_qty=3),
                PackagingRecord(work_order_id=wo.id, packed_qty=2, total_packed_quantity=2),
                Package(package_no=f"H-PKG-{target.id}-{suffix}", barcode=f"H-BC-{target.id}-{suffix}", production_order_id=target.id, model_id=case["model_id"], color="white", total_quantity=2, capacity=10, status="shipped"),
                StockMovement(item_id=item.id, movement_type="issue", quantity=3, unit="kg", reference_type="ProductionOrder", reference_id=target.id),
            ])
        invoice = Invoice(sales_order_id=so.id, invoice_no=f"H-INV-{suffix}", amount=60)
        db.add(invoice)
        db.flush()
        db.add(Payment(invoice_id=invoice.id, amount=15))
        db.flush()
        sales_package = db.query(Package).filter(Package.production_order_id == po.id).one()
        shipment = Shipment(shipment_no=f"H-SH-{suffix}", sales_order_id=None)
        db.add(shipment)
        db.flush()
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=sales_package.id, quantity=2))
        sales_id, stock_id = int(so.id), int(stock.id)

    with sessions() as db:
        payload = history_service.list_sales_order_history(db, page_size=50)
        rows = {(row["record_type"], row["id"]): row for row in payload}
        sales_row = rows[("sales_order", sales_id)]
        stock_row = rows[("production_order", stock_id)]
        assert sales_row == history_service._sales_order_history(db, db.get(SalesOrder, sales_id))
        assert stock_row == history_service._stock_production_history(db, db.get(ProductionOrder, stock_id))
        for row in (sales_row, stock_row):
            summary = row["summary"]
            assert [summary[key] for key in ("cut_qty", "cut_passed_qty", "printed_qty", "sewn_qty", "sewn_passed_qty", "packed_record_qty", "packaged_qty", "shipped_qty")] == [7, 6, 5, 4, 3, 2, 2, 2]
            assert summary["material_spent_cost"] == 6
            assert summary["material_spent"][0]["quantity"] == 3
        assert sales_row["summary"]["invoice_total"] == 60
        assert sales_row["summary"]["paid_total"] == 15
        assert sales_row["summary"]["outstanding_amount"] == 86
        assert sales_row["summary"]["shipment_count"] == 1
        assert stock_row["summary"]["invoice_count"] == 0
        sales_detail = history_service.get_sales_order_history(sales_id, db)
        stock_detail = history_service.get_stock_production_history(stock_id, db)
        for key, value in sales_row.items():
            assert sales_detail[key] == value
        for key, value in stock_row.items():
            assert stock_detail[key] == value
        assert len(sales_detail["invoices"]) == 1
        assert len(sales_detail["payments"]) == 1
        assert len(stock_detail["packages"]) == 1


def test_history_route_rejects_unauthenticated_access(client):
    response = client.get("/api/sales-orders/history")
    assert response.status_code in (401, 403)


def test_rich_stock_page_does_not_expand_child_id_parameters(pg):
    from uuid import uuid4
    from app.schemas import CuttingRecord, Department, Package, ProductionOrder, WorkOrder

    engine, sessions = pg
    case = _seed(sessions, rows=[(1, "draft", "client_order", "draft")])
    suffix = uuid4().hex[:8]
    with sessions.begin() as db:
        dep = Department(name=f"Bound {suffix}", code=f"B{suffix}")
        db.add(dep)
        db.flush()
        po = db.get(ProductionOrder, case["production_ids"][0])
        wo = WorkOrder(production_order_id=po.id, department_id=dep.id, operation="cutting")
        db.add(wo)
        db.flush()
        db.add_all([CuttingRecord(work_order_id=wo.id, cut_pieces=1) for _ in range(1005)])
        db.add_all([
            Package(package_no=f"B-{suffix}-{i}", barcode=f"BB-{suffix}-{i}",
                    production_order_id=po.id, model_id=po.model_id, color="white",
                    total_quantity=1, capacity=10)
            for i in range(1005)
        ])
    statements = []

    def record(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", record)
    try:
        with sessions() as db:
            rows = history_service.list_sales_order_history(db, order_type="branded_stock", page_size=1)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert rows[0]["summary"]["cut_qty"] == 1005
    assert rows[0]["summary"]["package_count"] == 1005
    # SQLAlchemy's own select-in relationship loaders may chunk independently.
    # Every individual SELECT remains below the database's low bind limit.
    assert max(len(parameters) for _, parameters in statements) <= 500


def test_shipment_and_package_hydration_is_limited_to_summary_needs(pg):
    from uuid import uuid4
    from app.schemas import (
        Package, PackageItem, PackageScanLog, ProductionOrder, SalesOrder,
        Shipment, ShipmentPackage,
    )

    engine, sessions = pg
    case = _seed(sessions, rows=[(2, "draft", "client_order", "draft"), (1, "draft", "client_order", "draft")])
    suffix = uuid4().hex[:8]
    with sessions.begin() as db:
        so1, so2 = [db.get(SalesOrder, sid) for sid in case["sales_ids"]]
        stock = db.get(ProductionOrder, case["production_ids"][1])
        sales_po = ProductionOrder(production_no=f"L-PO-{suffix}", production_type="client_order", sales_order_id=so1.id, model_id=case["model_id"], planned_quantity=2)
        db.add(sales_po)
        db.flush()
        sales_pkg = Package(package_no=f"L-S-{suffix}", barcode=f"L-SB-{suffix}", production_order_id=sales_po.id, model_id=case["model_id"], color="white", total_quantity=2, capacity=10)
        others = [Package(package_no=f"L-{suffix}-{i}", barcode=f"LB-{suffix}-{i}", production_order_id=stock.id, model_id=case["model_id"], color="white", total_quantity=3, capacity=10) for i in range(100)]
        direct = Shipment(shipment_no=f"L-D-{suffix}", sales_order_id=so1.id)
        empty_direct = Shipment(shipment_no=f"L-E-{suffix}", sales_order_id=so2.id)
        db.add_all([sales_pkg, *others, direct, empty_direct])
        db.flush()
        db.add_all([ShipmentPackage(shipment_id=direct.id, package_id=sales_pkg.id, quantity=2),
                    ShipmentPackage(shipment_id=empty_direct.id, package_id=others[0].id, quantity=3)])
        db.add_all([ShipmentPackage(shipment_id=direct.id, package_id=pkg.id, quantity=1) for pkg in others])
        db.add_all([PackageItem(package_id=sales_pkg.id, model_id=case["model_id"], color="white", size=str(i), quantity=1) for i in range(12)])
        db.add_all([PackageScanLog(package_id=sales_pkg.id, scan_type="scan") for _ in range(12)])
        so1_id, so2_id = int(so1.id), int(so2.id)

    def measure(**filters):
        loaded = []
        package_query_rows = []
        with sessions() as db:
            def on_load(_session, entity):
                if isinstance(entity, (ShipmentPackage, PackageItem, PackageScanLog)):
                    loaded.append(entity)

            def on_sql(_conn, cursor, _sql, _params, context, _many):
                compiled = getattr(context, "compiled", None)
                statement = getattr(compiled, "statement", None)
                descriptions = getattr(statement, "column_descriptions", ()) or ()
                if any(entry.get("entity") is Package for entry in descriptions):
                    package_query_rows.append(cursor.rowcount)

            event.listen(db, "loaded_as_persistent", on_load)
            event.listen(engine, "after_cursor_execute", on_sql)
            try:
                result = history_service.list_sales_order_history(db, page_size=50, **filters)
            finally:
                event.remove(db, "loaded_as_persistent", on_load)
                event.remove(engine, "after_cursor_execute", on_sql)
            return result, loaded, package_query_rows

    stock_rows, stock_loaded, _ = measure(q="PERF25-PO-2", order_type="branded_stock")
    assert len(stock_rows) == 1
    assert not stock_loaded
    rows, loaded, package_query_rows = measure(customer_id=case["customer_id"])
    sales = {row["id"]: row for row in rows}
    assert sales[so1_id]["summary"]["shipped_qty"] == 2
    assert sales[so2_id]["summary"]["shipped_qty"] == 3
    assert sales[so1_id]["summary"]["shipment_count"] == 1
    assert sales[so2_id]["summary"]["shipment_count"] == 1
    assert sum(isinstance(row, ShipmentPackage) for row in loaded) == 2
    assert not any(isinstance(row, (PackageItem, PackageScanLog)) for row in loaded)
    assert package_query_rows == [1]
    with sessions() as db:
        for sid in (so1_id, so2_id):
            assert sales[sid] == history_service._sales_order_history(db, db.get(SalesOrder, sid))

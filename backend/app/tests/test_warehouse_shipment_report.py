from datetime import date, datetime, timezone
from io import BytesIO

from openpyxl import load_workbook

from app.db.session import SessionLocal
from app.libs.dto.fulfillment.shipment_report import ShipmentReportQuery
from app.models.fulfillment.shipment_report_service import shipment_report, shipment_report_workbook
from app.schemas import Shipment


def add_shipment(db, number, stamp, *, status="shipped", deleted=False, lines=None):
    shipment = Shipment(shipment_no=number, status=status, shipped_at=stamp,
                        deleted_at=stamp if deleted else None,
                        dispatch_snapshot={"document": {"customer": "=Exact client", "sales_order_no": "SO-2026-000121",
                            "lines": lines or [
                                {"model_no": "SJ-4044", "variant_no": "3372", "quantity": 12, "size": "M", "color": "Blue", "package_no": "PK-A"},
                                {"model_no": "SJ-4044", "variant_no": "3372", "quantity": 8, "size": "L", "color": "Blue", "package_no": "PK-A"},
                                {"model_no": "SJ-4044", "variant_no": "3373", "quantity": 5, "size": "M", "color": "Red", "package_no": "PK-B"},
                            ]}})
    db.add(shipment)
    db.flush()
    return shipment


def test_report_filters_real_dispatch_time_in_tashkent_and_counts_partial_packages_once():
    with SessionLocal() as db:
        add_shipment(db, "WR-BEFORE", datetime(2026, 11, 6, 18, 59, 59, tzinfo=timezone.utc))
        add_shipment(db, "WR-START", datetime(2026, 11, 6, 19, tzinfo=timezone.utc))
        add_shipment(db, "WR-END", datetime(2026, 11, 7, 18, 59, 59, tzinfo=timezone.utc), status="delivered")
        add_shipment(db, "WR-AFTER", datetime(2026, 11, 7, 19, tzinfo=timezone.utc))
        for status in ("draft", "created", "cancelled"):
            add_shipment(db, f"WR-{status}", datetime(2026, 11, 7, 5, tzinfo=timezone.utc), status=status)
        add_shipment(db, "WR-DELETED", datetime(2026, 11, 7, 5, tzinfo=timezone.utc), deleted=True)
        report = shipment_report(db, ShipmentReportQuery(date_from=date(2026, 11, 7), date_to=date(2026, 11, 7)))
        assert report.shipment_count == 2
        assert report.quantity == 50 and report.package_count == 4 and report.total == 4
        assert {row.shipment_no for row in report.rows} == {"WR-START", "WR-END"}
        matching = [row for row in report.rows if row.variant == "3372"]
        assert all(row.quantity == 20 and row.packages[0].quantity == 20 and len(row.packages) == 1 for row in matching)
        assert matching[0].sizes == {"M": 12, "L": 8}
        assert not db.dirty and not db.new and not db.deleted


def test_search_paging_and_export_share_the_same_frozen_quantities_and_literal_text():
    with SessionLocal() as db:
        add_shipment(db, "WR-EXPORT", datetime(2026, 11, 7, 8, tzinfo=timezone.utc))
        for term in ("3372", "V-3372", "SJ4044-V-3372", "SJ4044/V-3372", "SJ4044 / V-3372", "SJ4044-3372", "PK-A"):
            report = shipment_report(db, ShipmentReportQuery(q=term, page_size=1))
            assert report.total == 1 and report.quantity == 20
        report = shipment_report(db, ShipmentReportQuery(q="Exact client", page_size=1))
        assert report.total == 2 and len(report.rows) == 1 and report.quantity == 25
        assert shipment_report(db, ShipmentReportQuery(q="Exact client", page=2, page_size=1)).rows[0].variant == "3373"
        for lang, header in (("en", "Model"), ("ru", "Модель"), ("uz", "Model")):
            sheet = load_workbook(BytesIO(shipment_report_workbook(db, ShipmentReportQuery(q="3372"), lang))).active
            assert sheet["A1"].value == header
            assert sheet.max_row == 2 and sheet["C2"].value == 20
            assert sheet["D2"].value == 1 and sheet["E2"].value == "PK-A: 20"
            assert sheet["I2"].value == "=Exact client" and sheet["I2"].data_type == "s"
            assert sheet["J2"].value == datetime(2026, 11, 7, 13)
            assert sheet.freeze_panes == "A2" and sheet.auto_filter.ref == "A1:M2"


def test_report_api_permissions_queries_and_export(client, auth_headers):
    assert client.get("/api/warehouse-reports/shipments").status_code == 401
    with SessionLocal() as db:
        add_shipment(db, "WR-API", datetime(2026, 11, 7, 8, tzinfo=timezone.utc))
        db.commit()
    response = client.get("/api/warehouse-reports/shipments?q=3372&date_from=2026-11-07&date_to=2026-11-07", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 20
    assert client.get("/api/warehouse-reports/shipments?date_from=2026-11-08&date_to=2026-11-07", headers=auth_headers).status_code == 422
    assert client.get("/api/warehouse-reports/shipments?page_size=201", headers=auth_headers).status_code == 422
    export = client.get("/api/warehouse-reports/shipments.xlsx?q=3372&lang=ru", headers=auth_headers)
    assert export.status_code == 200, export.text[:100]
    assert load_workbook(BytesIO(export.content)).active["A1"].value == "Модель"


def test_report_refuses_nonwarehouse_actor(client):
    from app.core.deps import get_current_user
    from app.main import app
    from app.schemas import Role, User
    with SessionLocal() as db:
        role = Role(name="Report denied", permissions=["modeling.models"])
        db.add(role); db.flush()
        user = User(name="Report denied", email="report-denied@example.com", password_hash="unused", role_id=role.id, is_active=True)
        db.add(user); db.commit(); db.refresh(user)
        user.role
        app.dependency_overrides[get_current_user] = lambda: user
        try:
            assert client.get("/api/warehouse-reports/shipments").status_code == 403
            assert client.get("/api/warehouse-reports/shipments.xlsx").status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)


def test_old_consumed_package_keeps_shipment_link_quantity_and_unknown_size():
    from app.schemas import Model, Package, PackageItem, LegacyStockReceipt, ShipmentPackage
    with SessionLocal() as db:
        model = db.query(Model).first()
        receipt = LegacyStockReceipt(source_system="WR", source_warehouse_id="QA", source_record_id="old", source_checksum="0" * 64, source_payload={})
        db.add(receipt); db.flush()
        package = Package(package_no="WR-OLD", barcode="WR-OLD", model_id=model.id, legacy_receipt_id=receipt.id,
                          color="Blue", total_quantity=20, capacity=20, status="shipped", dispatched_quantity=20)
        db.add(package); db.flush()
        item = PackageItem(package_id=package.id, model_id=model.id, size="M", color="Blue", quantity=20)
        db.add(item); db.flush()
        package.dispatched_quantities = {str(item.id): 20}
        shipment = Shipment(shipment_no="WR-OLD-SHIP", status="shipped", shipped_at=datetime(2026, 11, 7, 8, tzinfo=timezone.utc))
        db.add(shipment); db.flush()
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=20)); db.flush()
        report = shipment_report(db, ShipmentReportQuery(q="WR-OLD-SHIP", date_from=date.min, date_to=date.max))
        assert report.quantity == 20 and report.shipment_count == 1 and report.package_count == 1
        assert report.rows[0].historical_reconstruction
        assert report.rows[0].sizes == {"—": 20}
        assert report.rows[0].packages[0].quantity == 20

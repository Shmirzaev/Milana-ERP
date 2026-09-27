from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import LegacyStockReceipt, Model, Package, Shipment, ShipmentPackage


def test_shipment_scan_status_projects_attached_package_ids(client, auth_headers):
    marker = uuid4().hex[:12].upper()
    with SessionLocal() as db:
        model = db.query(Model).first()
        shipment = Shipment(shipment_no=f"STATUS-{marker}", status="draft")
        receipt = LegacyStockReceipt(
            source_system="TEST",
            source_warehouse_id="shipment-scan-status",
            source_record_id=marker,
            source_checksum=marker.ljust(64, "0"),
            source_payload={"test": True},
        )
        db.add(receipt)
        db.flush()
        package = Package(
            package_no=f"STATUS-P-{marker}",
            barcode=f"STATUS-B-{marker}",
            legacy_receipt_id=receipt.id,
            model_id=model.id,
            color="navy",
            total_quantity=3,
            capacity=3,
            status="received_in_storage",
        )
        db.add_all([shipment, package])
        db.flush()
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=3))
        shipment_id = int(shipment.id)
        db.commit()

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and (
            " from shipments " in normalized or " from shipment_packages " in normalized
        ):
            statements.append(normalized)

    event.listen(SessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/shipments/{shipment_id}/scan-status", headers=auth_headers)
    finally:
        event.remove(SessionLocal.kw["bind"], "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.json()["required_count"] == 1
    assert response.json()["scanned_count"] == 0
    assert response.json()["remaining_count"] == 1
    shipment_reads = [statement for statement in statements if " from shipments " in statement]
    package_link_reads = [statement for statement in statements if " from shipment_packages " in statement]
    assert len(shipment_reads) == 1
    assert "shipments.id" in shipment_reads[0].split(" from shipments", 1)[0]
    assert "shipments.dispatch_snapshot" not in shipment_reads[0]
    assert len(package_link_reads) == 1
    selected = package_link_reads[0].split(" from shipment_packages", 1)[0]
    assert "shipment_packages.package_id" in selected
    assert "shipment_packages.shipment_id" in selected
    assert "shipment_packages.quantity" not in selected

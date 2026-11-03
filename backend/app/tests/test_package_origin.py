"""Literal legacy identities and batch-grain sewing evidence, never routing guesses."""

import pytest
from sqlalchemy import event

from app.schemas import (
    Department, LegacyStockReceipt, Model, Package, PackageBatchAllocation,
    ProductionBatch, ProductionOrder, SewingAssignment, SewingFlow, SewingRecord, WorkOrder,
)
from app.tests.conftest import TestSessionLocal, test_engine


def _seed():
    with TestSessionLocal() as db:
        model = Model(code="ORIGIN-CATALOG", name="Origin model")
        db.add(model)
        db.flush()
        order = ProductionOrder(production_no="PO-ORIGIN", production_type="branded_stock", model_id=model.id, planned_quantity=100)
        db.add(order)
        db.flush()
        batches = [ProductionBatch(production_order_id=order.id, batch_no=str(n), planned_quantity=30) for n in (1, 2, 3)]
        db.add_all(batches)
        db.flush()
        # The sewing work order's department and the packaging department are
        # Milana, while the actual assignment's line belongs to ECO Cotton.
        department = db.query(Department).filter_by(code="MIL").one()
        work = WorkOrder(production_order_id=order.id,
                         department_id=department.id, operation="sewing", planned_output_qty=100)
        db.add(work)
        db.flush()
        for batch, factory, sewn in zip(batches, ["ECO", "MIL", "BST"], [30, 30, 0]):
            flow = SewingFlow(name=f"Origin {factory}", code=f"ORIGIN-{factory}", factory_code=factory)
            db.add(flow)
            db.flush()
            assignment = SewingAssignment(work_order_id=work.id, production_batch_id=batch.id,
                                           sewing_flow_id=flow.id, quantity=30)
            db.add(assignment)
            db.flush()
            db.add(SewingRecord(work_order_id=work.id, production_batch_id=batch.id,
                               sewing_assignment_id=assignment.id, sewn_qty=sewn))
        packages = []
        for index, batch in enumerate(batches):
            package = Package(package_no=f"PKG-ORIGIN-{index}", barcode=f"ORIGIN-{index}",
                              production_order_id=order.id, production_batch_id=batch.id,
                              model_id=model.id, color="Blue", total_quantity=10, capacity=60,
                              qr_code_url="/synthetic/origin", status="received_in_storage")
            db.add(package)
            packages.append(package)
        db.flush()
        mixed = Package(package_no="PKG-ORIGIN-MIX", barcode="ORIGIN-MIX", production_order_id=order.id,
                        production_batch_id=batches[2].id, model_id=model.id, color="Blue", total_quantity=20,
                        capacity=60, qr_code_url="/synthetic/origin", status="received_in_storage")
        db.add(mixed)
        db.flush()
        db.add_all([PackageBatchAllocation(package_id=mixed.id, production_batch_id=batch.id, quantity=10) for batch in batches[:2]])
        db.commit()
        return [p.id for p in packages], mixed.id


def test_factory_filter_is_before_pagination_and_uses_sewing_output(client, auth_headers):
    ids, mixed = _seed()
    response = client.get("/api/packages?include_total=true&page_size=1&sewing_factory_code=ECO", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert response.json()["rows"][0]["id"] == mixed
    assert response.json()["rows"][0]["sewing_factory_codes"] == ["ECO", "MIL"]
    response = client.get("/api/packages?include_total=true&page_size=1&page=2&sewing_factory_code=ECO", headers=auth_headers)
    assert response.json()["rows"][0]["id"] == ids[0]
    assert response.json()["rows"][0]["sewing_factory_code"] == "ECO"
    # A planned assignment and a zero-output sewing record are not evidence.
    assert client.get("/api/packages?sewing_factory_code=BST", headers=auth_headers).json() == []
    assert client.get("/api/packages?sewing_factory_code=INVALID", headers=auth_headers).status_code == 422
    assert client.get("/api/packages?sewing_factory_code=ECO").status_code == 401


def test_warehouse_projection_filter_and_single_scan_share_origin(client, auth_headers):
    ids, mixed = _seed()
    response = client.get("/api/packages/storage-map?include_unplaced=true&sewing_factory_code=ECO", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = response.json()["placements"]
    assert {row["id"] for row in rows} == {ids[0], mixed}
    assert response.json()["summary"]["packages_in_storage"] == 2
    scanned = client.get("/api/packages/barcode/ORIGIN-0", headers=auth_headers)
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["sewing_factory_codes"] == ["ECO"]
    assert next(row for row in rows if row["id"] == ids[0])["sewing_factory_codes"] == ["ECO"]
    unknown = client.get(f"/api/packages/{ids[2]}", headers=auth_headers).json()
    assert unknown["sewing_factory_codes"] == [] and unknown["sewing_factory_code"] is None


@pytest.mark.parametrize("linked_model", [False, True])
def test_legacy_scan_keeps_literal_sticker_model_and_variant(client, auth_headers, linked_model):
    with TestSessionLocal() as db:
        model = Model(code="DIFFERENT-999", name="Catalog changed after import") if linked_model else None
        if model:
            db.add(model)
            db.flush()
        receipt = LegacyStockReceipt(source_system="UZERP", source_warehouse_id="18", source_record_id="origin-legacy",
            source_checksum="a" * 64, source_payload={"model_number": "TJ2049", "article": "V-4326"})
        db.add(receipt)
        db.flush()
        package = Package(package_no="OLD-ORIGIN", barcode="uzerp_ii_1234_2", legacy_receipt_id=receipt.id,
                          model_id=model.id if model else None, color="Blue", total_quantity=60, capacity=60, qr_code_url="/synthetic/legacy")
        db.add(package)
        db.commit()
    response = client.get("/api/packages/barcode/uzerp_ii_1234_2", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["model_no"] == "TJ2049"
    assert response.json()["variant_no"] == "V-4326"
    assert (response.json()["model_id"] is not None) is linked_model
    assert response.json()["sewing_factory_codes"] == []


def test_historical_sewing_without_assignment_uses_record_department(client, auth_headers):
    ids, _mixed = _seed()
    with TestSessionLocal() as db:
        package = db.get(Package, ids[0])
        record = db.query(SewingRecord).filter_by(production_batch_id=package.production_batch_id).one()
        record.sewing_assignment_id = None
        db.commit()
    result = client.get(f"/api/packages/{ids[0]}", headers=auth_headers)
    assert result.status_code == 200, result.text
    assert result.json()["sewing_factory_code"] == "MIL"


@pytest.mark.parametrize("model_number,article", [("", ""), ("TJ2049", ""), ("", "V-4326")])
def test_v3_unresolved_sticker_never_exposes_hidden_model_hash(client, auth_headers, model_number, article):
    # Mirrors ops/import_completed_packs.py:create_hidden_model for a v3
    # manifest that legitimately lacks either or both original business numbers.
    with TestSessionLocal() as db:
        model = Model(code="LEGACY-STICKER-0123456789ABCDEF", name="Unknown model / Unknown variant",
                      category="Legacy finished goods", status="approved", details_json={
                          "legacy_import": True,
                          "legacy_original_model_no": model_number,
                          "legacy_original_variant_no": article,
                          "general": {"model_no": model_number, "variant_no": article},
                      })
        db.add(model)
        db.flush()
        receipt = LegacyStockReceipt(source_system="UZERP_STICKER_PHOTO", source_warehouse_id="18",
                                    source_record_id="unknown-origin", source_checksum="a" * 64,
                                    source_payload={"model_number": model_number, "article": article})
        db.add(receipt)
        db.flush()
        db.add(Package(package_no="OLD-UNKNOWN-ORIGIN", barcode="uzerp_ii_67890_2", model_id=model.id,
                       legacy_receipt_id=receipt.id, color="Blue", total_quantity=60, capacity=60,
                       qr_code_url="/synthetic/legacy"))
        db.commit()
    scanned = client.get("/api/packages/barcode/uzerp_ii_67890_2", headers=auth_headers)
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["model_no"] == (model_number or None)
    assert scanned.json()["variant_no"] == (article or None)
    listed = client.get("/api/packages", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["model_no"] == (model_number or None)
    assert listed.json()[0]["variant_no"] == (article or None)


def test_origin_query_count_does_not_grow_with_packages(client, auth_headers):
    _seed()
    counts = []
    for size in (1, 4):
        statements = []
        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            result = client.get(f"/api/packages?page_size={size}&sewing_factory_code=ECO", headers=auth_headers)
            assert result.status_code == 200, result.text
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        counts.append(len(statements))
    assert counts[0] == counts[1]

"""Physical receipt and exact print-run handoff regressions (isolated test DB)."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    AuditLog, Department, FinishedGoodsStock, ManualPackageReceipt, Model, Package,
    PackageBarcodeAlias, PackagePrintRun, PackagePrintRunMember,
    PackageScanLog, PackagingRecord, ProductionOrder, WorkOrder,
)

BASE = "/api/packages"


@pytest.fixture
def warehouse(client):
    login = client.post("/api/auth/token", data={"username": "fgs@example.com", "password": "demo12345"})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def manual_body(**overrides):
    with SessionLocal() as db:
        model = db.query(Model).filter(Model.code == "T-SHIRT-001").one()
        return {"request_key": str(uuid4()), "model_id": model.id, "color": "White", "weight_kg": 1.5,
                "count": 2, "sizes": [{"size": model.sizes[0].size, "quantity": 4}],
                "reason": "Physical packs counted on receipt", **overrides}


@pytest.fixture
def packaging_order():
    with SessionLocal() as db:
        model = db.query(Model).filter(Model.code == "T-SHIRT-001").one()
        po = ProductionOrder(production_no="PO-PRINT-TEST", production_type="branded_stock", model_id=model.id,
                             planned_quantity=20)
        db.add(po)
        db.flush()
        wo = WorkOrder(production_order_id=po.id, department_id=db.query(Department.id).filter(Department.code == "PKG").scalar(),
                       operation="packaging", planned_input_qty=20, planned_output_qty=20, passed_qty=20, status="in_progress")
        db.add(wo)
        db.flush()
        db.add(PackagingRecord(work_order_id=wo.id, packed_qty=20, input_qty=20))
        db.commit()
        return {"production_order_id": po.id, "model_id": model.id, "color": "White", "capacity": 60,
                "weight_kg": 1.5, "items": [{"model_id": model.id, "color": "White", "size": model.sizes[0].size, "quantity": 2}]}


def create_run(client, headers, template, count):
    body = {"request_key": str(uuid4()), "packages": [template for _ in range(count)]}
    result = client.post(BASE + "/print-runs/create-packages", headers=headers, json=body)
    assert result.status_code == 201, result.text
    assert client.post(BASE + "/print-runs/create-packages", headers=headers, json=body).json() == result.json()
    return result.json()


def package_qr(pid):
    with SessionLocal() as db:
        p = db.get(Package, pid)
        return f"PACKAGE:{p.package_no}|{p.barcode}"


def stock_fingerprint():
    with SessionLocal() as db:
        return db.execute(select(FinishedGoodsStock.__table__).order_by(FinishedGoodsStock.id)).all()


def test_manual_receipt_once_with_real_source_and_reprints(client, warehouse):
    body = manual_body()
    with SessionLocal() as db:
        orders = db.query(ProductionOrder).count()
    response = client.post(BASE + "/manual-receipt", headers=warehouse, json=body)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert client.post(BASE + "/manual-receipt", headers=warehouse, json=body).json() == saved
    conflict = client.post(BASE + "/manual-receipt", headers=warehouse, json={**body, "count": 3})
    assert conflict.status_code == 409
    before = stock_fingerprint()
    for _ in range(2):
        label = client.get(BASE + f"/print-runs/{saved['print_run']['id']}/label", headers=warehouse)
        assert label.status_code == 200, label.text
    with SessionLocal() as db:
        assert db.query(ProductionOrder).count() == orders
        assert db.query(ManualPackageReceipt).count() == 1
        receipt = db.get(ManualPackageReceipt, saved["receipt_id"])
        assert receipt.evidence["reason"] == body["reason"]
        packs = db.query(Package).filter(Package.manual_receipt_id == receipt.id).all()
        assert len(packs) == 2
        assert all(p.production_order_id is None and p.legacy_receipt_id is None and p.status == "received_in_storage" for p in packs)
        assert db.query(AuditLog).filter(AuditLog.action == "manual_receipt").count() == 1
    assert before == stock_fingerprint()
    lookup = client.get(BASE + f"/{saved['print_run']['package_ids'][0]}", headers=warehouse)
    assert lookup.json()["manual_source"]["receipt_no"] == saved["receipt_no"]


def test_six_then_four_receive_by_actual_package_qr_and_alias(client, auth_headers, warehouse, packaging_order):
    first = create_run(client, auth_headers, packaging_order, 6)
    second = create_run(client, auth_headers, packaging_order, 4)
    assert len(first["package_ids"]) == 6 and len(second["package_ids"]) == 4
    assert not set(first["package_ids"]) & set(second["package_ids"])
    before = stock_fingerprint()
    for _ in range(2):
        assert client.get(BASE + f"/print-runs/{first['id']}/label", headers=warehouse).status_code == 200
    scan = package_qr(first["package_ids"][3])
    resolved = client.get(BASE + "/print-runs/resolve", params={"code": scan}, headers=warehouse)
    assert resolved.json()["print_run"]["package_ids"] == first["package_ids"]
    received = client.post(BASE + "/print-runs/receive", json={"code": scan, "storage_cell": "A-01", "storage_shelf": "S1"}, headers=warehouse)
    assert received.status_code == 200, received.text
    assert received.json()["count"] == 6
    with SessionLocal() as db:
        assert {p.status for p in db.query(Package).filter(Package.id.in_(second["package_ids"]))} == {"packed"}
        db.add(PackageBarcodeAlias(package_id=second["package_ids"][2], code="UNIQUE-SECOND-RUN", code_type="legacy"))
        db.commit()
    for _ in range(2):
        result = client.post(BASE + "/print-runs/receive", json={"code": "UNIQUE-SECOND-RUN"}, headers=warehouse)
        assert result.status_code == 200, result.text
        assert result.json()["count"] == 4
    repeated = client.post(BASE + "/print-runs/receive", json={"code": package_qr(first["package_ids"][0])}, headers=warehouse)
    assert repeated.status_code == 200
    with SessionLocal() as db:
        assert db.query(PackageScanLog).filter(PackageScanLog.scan_type == "received_storage").count() == 10
        assert db.query(PackagePrintRun).count() == 2
    assert before == stock_fingerprint()


def test_group_member_cannot_receive_individually_or_regroup(client, auth_headers, warehouse, packaging_order):
    run = create_run(client, auth_headers, packaging_order, 6)
    pid = run["package_ids"][0]
    assert client.post(BASE + f"/{pid}/receive-storage", headers=warehouse, json={}).status_code == 409
    assert client.post(BASE + "/batch/receive-storage", headers=warehouse, json={"package_ids": [pid]}).status_code == 409
    assert client.post(BASE + "/print-runs", headers=warehouse, json={"request_key": str(uuid4()), "package_ids": [pid]}).status_code == 409
    with SessionLocal() as db:
        assert all(p.status == "packed" for p in db.query(Package).filter(Package.id.in_(run["package_ids"])))
    assert client.post(BASE + "/print-runs/receive", headers=warehouse, json={"code": package_qr(pid)}).status_code == 200


def test_ambiguous_alias_and_changed_member_roll_back_whole_receipt(client, auth_headers, warehouse, packaging_order):
    run = create_run(client, auth_headers, packaging_order, 6)
    with SessionLocal() as db:
        for pid in run["package_ids"][:2]:
            db.add(PackageBarcodeAlias(package_id=pid, code="AMBIGUOUS", code_type="legacy"))
        db.commit()
    assert client.post(BASE + "/print-runs/receive", headers=warehouse, json={"code": "AMBIGUOUS"}).status_code == 409
    with SessionLocal() as db:
        p = db.get(Package, run["package_ids"][-1])
        p.weight_kg = 9
        db.commit()
    assert client.post(BASE + "/print-runs/receive", headers=warehouse, json={"code": package_qr(run["package_ids"][0])}).status_code == 409
    assert client.get(BASE + f"/print-runs/{run['id']}/label", headers=warehouse).status_code == 409
    with SessionLocal() as db:
        assert all(p.status == "packed" for p in db.query(Package).filter(Package.id.in_(run["package_ids"])))
        assert db.query(PackageScanLog).filter(PackageScanLog.scan_type == "received_storage").count() == 0


def test_received_run_reprints_current_quantities_after_audited_correction(client, auth_headers, warehouse):
    from app.models import Customer, PackageItem, PackageQuantityAdjustment
    body = manual_body()
    created = client.post(BASE + "/manual-receipt", headers=warehouse, json=body)
    assert created.status_code == 201, created.text
    saved = created.json()
    run = saved["print_run"]
    ids = run["package_ids"]
    with SessionLocal() as db:
        original_members = db.execute(select(PackagePrintRunMember.__table__).order_by(PackagePrintRunMember.id)).all()
        original_receipt = db.get(ManualPackageReceipt, saved["receipt_id"]).evidence
        customer_id = db.query(Customer.id).first()[0]
    sale = client.post("/api/sales-orders", headers=auth_headers, json={
        "customer_id": customer_id, "order_type": "branded_stock_sale", "items": [{
            "model_id": body["model_id"], "color": "mixed", "size": "any", "requested_pack_count": 2,
            "unit_price": 10, "source_type": "from_stock",
        }],
    })
    assert sale.status_code == 201, sale.text
    shipment = client.post("/api/shipments", headers=warehouse, json={"sales_order_id": sale.json()["id"]})
    assert shipment.status_code == 201, shipment.text
    sid = shipment.json()["id"]
    for pid in ids:
        scanned = client.post(f"/api/shipments/{sid}/scan-package", headers=warehouse, json={"code": package_qr(pid)})
        assert scanned.status_code == 200, scanned.text
    with SessionLocal() as db:
        item_id = db.query(PackageItem.id).filter(PackageItem.package_id == ids[0]).scalar()
    corrected = client.post(f"/api/shipments/{sid}/packages/{ids[0]}/quantity", headers=warehouse, json={
        "expected_quantity": 4, "reason": "Physical shortage found before dispatch",
        "items": [{"item_id": item_id, "quantity": 3}],
    })
    assert corrected.status_code == 200, corrected.text
    before = stock_fingerprint()
    with SessionLocal() as db:
        assert db.query(PackageQuantityAdjustment).filter(PackageQuantityAdjustment.package_id == ids[0]).count() == 1
        packages_before = db.execute(select(Package.__table__).order_by(Package.id)).all()
    for _ in range(2):
        label = client.get(BASE + f"/print-runs/{run['id']}/label", headers=warehouse)
        assert label.status_code == 200, label.text
        assert "Pieces / Изделия / Dona: 7</p>" in label.text
        assert label.text.count("<article class='label'") == 2
    assert stock_fingerprint() == before
    with SessionLocal() as db:
        assert db.execute(select(Package.__table__).order_by(Package.id)).all() == packages_before
        assert db.execute(select(PackagePrintRunMember.__table__).order_by(PackagePrintRunMember.id)).all() == original_members
        assert db.get(ManualPackageReceipt, saved["receipt_id"]).evidence == original_receipt
        assert db.get(PackagePrintRun, run["id"]).package_ids == ids
        member = db.query(PackagePrintRunMember).filter(PackagePrintRunMember.run_id == run["id"]).first()
        db.delete(member)
        db.commit()
    assert client.get(BASE + f"/print-runs/{run['id']}/label", headers=warehouse).status_code == 409


@pytest.mark.parametrize("change", [{"count": 0}, {"count": 1.5}, {"weight_kg": -1}, {"production_order_id": 99},
                                    {"sizes": [{"size": "unconfigured", "quantity": 3}]}])
def test_manual_validation_never_creates_stock(client, warehouse, change):
    before = stock_fingerprint()
    result = client.post(BASE + "/manual-receipt", headers=warehouse, json=manual_body(**change))
    assert result.status_code in (400, 422), result.text
    with SessionLocal() as db:
        assert db.query(ManualPackageReceipt).count() == 0
    assert stock_fingerprint() == before


def test_print_creation_requires_packaging_evidence_and_is_atomic(client, auth_headers, packaging_order):
    with SessionLocal() as db:
        db.query(PackagingRecord).delete()
        db.commit()
    before = stock_fingerprint()
    body = {"request_key": str(uuid4()), "packages": [packaging_order]}
    result = client.post(BASE + "/print-runs/create-packages", headers=auth_headers, json=body)
    assert result.status_code == 409, result.text
    assert stock_fingerprint() == before


def test_over_remaining_capacity_rolls_back_all_packages(client, auth_headers, packaging_order):
    before = stock_fingerprint()
    result = client.post(BASE + "/print-runs/create-packages", headers=auth_headers,
                         json={"request_key": str(uuid4()), "packages": [packaging_order] * 11})
    assert result.status_code == 400, result.text
    assert stock_fingerprint() == before
    with SessionLocal() as db:
        assert db.query(PackagePrintRun).count() == 0
        assert db.query(Package).filter(Package.production_order_id == packaging_order["production_order_id"]).count() == 0


def test_receipt_requires_storage_permission(client, auth_headers):
    login = client.post("/api/auth/token", data={"username": "planning@example.com", "password": "demo12345"})
    assert login.status_code == 200, login.text
    planning = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.post(BASE + "/manual-receipt", headers=planning, json=manual_body()).status_code == 403
    assert client.post(BASE + "/print-runs/receive", headers=planning, json={"code": "missing"}).status_code == 403


def test_shortage_does_not_release_consumed_packaging_capacity(client, auth_headers, packaging_order):
    from app.services.packages import _existing_package_totals_by_batch
    run = create_run(client, auth_headers, packaging_order, 10)
    with SessionLocal() as db:
        pkg = db.get(Package, run["package_ids"][0])
        pkg.total_quantity -= 1
        pkg.quantity_shortfall += 1
        db.commit()
        assert _existing_package_totals_by_batch(db, packaging_order["production_order_id"]) == {None: 20}
    one_piece = {**packaging_order, "items": [{**packaging_order["items"][0], "quantity": 1}]}
    result = client.post(BASE + "/print-runs/create-packages", headers=auth_headers,
                         json={"request_key": str(uuid4()), "packages": [one_piece]})
    assert result.status_code == 400, result.text


def test_print_manifest_cannot_silently_gain_a_member(client, auth_headers, warehouse, packaging_order):
    run = create_run(client, auth_headers, packaging_order, 6)
    with SessionLocal() as db:
        member = db.query(PackagePrintRunMember).filter(PackagePrintRunMember.run_id == run["id"]).first()
        # Simulate corrupted metadata; production triggers additionally reject this write.
        db.delete(member)
        db.commit()
    assert client.get(BASE + f"/print-runs/{run['id']}", headers=warehouse).status_code == 409


def test_stale_resolved_run_refreshes_receipt_after_lock(client, auth_headers, packaging_order, monkeypatch):
    from datetime import datetime, timezone
    from app.models import User
    from app.schemas.package_workflows import PrintRunReceiveIn
    from app.services import package_workflows as service
    run = create_run(client, auth_headers, packaging_order, 6)
    with SessionLocal() as db:
        stale = db.get(PackagePrintRun, run["id"])
        assert stale.received_at is None
        with SessionLocal() as other:
            completed = other.get(PackagePrintRun, run["id"])
            completed.received_at = datetime.now(timezone.utc)
            completed.received_by = 1
            other.commit()
        monkeypatch.setattr(service, "resolve_run", lambda *_: stale)
        refreshed, packages = service.receive_run(db, db.get(User, 1), PrintRunReceiveIn(code=run["code"]))
        assert refreshed.received_at is not None
        assert packages == []


def test_pending_correction_cannot_change_newly_grouped_package(client, auth_headers, warehouse, packaging_order):
    created = client.post(BASE, headers=auth_headers, json=packaging_order)
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    request = client.post(BASE + f"/{pid}/change-requests", headers=auth_headers,
                          json={"request_type": "delete", "reason": "Test correction before print grouping"})
    assert request.status_code == 201, request.text
    run = client.post(BASE + "/print-runs", headers=auth_headers,
                      json={"request_key": str(uuid4()), "package_ids": [pid]})
    assert run.status_code == 201, run.text
    approval = client.post(BASE + f"/change-requests/{request.json()['id']}/approve", headers=auth_headers)
    assert approval.status_code == 409, approval.text
    assert client.post(BASE + "/print-runs/receive", headers=warehouse, json={"code": package_qr(pid)}).status_code == 200


def test_0115_migration_roundtrip_preserves_existing_packages():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text, inspect

    path = Path(__file__).parents[2] / "alembic" / "versions" / "0115_package_print_runs.py"
    spec = importlib.util.spec_from_file_location("package_workflow_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("""CREATE TABLE packages (id INTEGER PRIMARY KEY, production_order_id INTEGER,
            legacy_receipt_id INTEGER, production_batch_id INTEGER, sales_order_id INTEGER,
            CONSTRAINT ck_packages_source_evidence CHECK (production_order_id IS NOT NULL OR legacy_receipt_id IS NOT NULL))"""))
        connection.execute(text("INSERT INTO packages (id, production_order_id) VALUES (1, 12)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(text("SELECT quantity_shortfall, manual_receipt_id FROM packages")).one() == (0, None)
        assert "package_print_runs" in inspect(connection).get_table_names()
        migration.downgrade()
        assert connection.execute(text("SELECT id, production_order_id FROM packages")).one() == (1, 12)
        assert "manual_package_receipts" not in inspect(connection).get_table_names()
    engine.dispose()

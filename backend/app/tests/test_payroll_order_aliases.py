import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.payroll import _canonical_payroll_snapshot
from app.core.order_reference import canonical_order_reference
from app.models import Department, PayrollQrLabel, PayrollRecord, ProductionOrder, SalesOrder, WorkOrder
from app.models.order_reference import BusinessOrderAlias
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee, _create_user_with_permissions


OLD_PO, NEW_PO = "PO-2026-000606", "PO-0606"
OLD_SO, NEW_SO = "SO-2026-000202", "SO-0202"


def _orders(*, canonical=True):
    with TestSessionLocal() as db:
        sales = SalesOrder(order_no=NEW_SO if canonical else OLD_SO, status="confirmed")
        db.add(sales)
        db.flush()
        production = ProductionOrder(production_no=NEW_PO if canonical else OLD_PO, sales_order_id=sales.id,
                                     model_id=1, production_type="client_order", planned_quantity=20)
        db.add(production)
        db.flush()
        department = db.query(Department).filter(Department.code == "MIL").one()
        db.add(WorkOrder(production_order_id=production.id, department_id=department.id, operation="sewing"))
        if canonical:
            db.add_all([
                BusinessOrderAlias(namespace="PO", entity_id=production.id, reference=OLD_PO, canonical_reference=NEW_PO),
                BusinessOrderAlias(namespace="SO", entity_id=sales.id, reference=OLD_SO, canonical_reference=NEW_SO),
            ])
        db.commit()
        return production.id, sales.id


def _compact(po, so, uid):
    return f"MW2*{po}*{OLD_PO}*-*1*1*MODEL*sewing*SEW-1*Sew sleeve*12*250*UZS*1*{so}*{OLD_SO}*-*1*{uid}*L"


def test_legacy_printed_payroll_qr_keeps_identity_rates_and_new_printed_refs(client, auth_headers):
    po, so = _orders()
    employee = _create_employee(client, auth_headers)
    uid = f"PY:{uuid4().hex}"
    original = _compact(po, so, uid)
    issued = client.post("/api/payroll/qr-labels/issue", headers=auth_headers, json={"labels": [{
        "label_uid": uid, "payload": original, "production_order_id": po, "sales_order_id": so,
        "production_no": OLD_PO, "sales_order_no": OLD_SO, "operation_section": "sewing",
        "operation_code": "SEW-1", "operation_name": "Sew sleeve", "quantity": 12,
        "rate_per_piece": 250, "size": "L",
    }]})
    assert issued.status_code == 200, issued.text
    token = issued.json()["labels"][0]["qr_token"]
    with TestSessionLocal() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=uid).one()
        assert (label.production_no, label.sales_order_no) == (NEW_PO, NEW_SO)
        persisted_parts = label.payload.split("*")
        expected_parts = original.split("*")
        expected_parts[2], expected_parts[15] = NEW_PO, NEW_SO
        assert persisted_parts == expected_parts  # UID and every non-reference byte unchanged.
        assert label.label_uid == uid
    scanned = client.post("/api/payroll/records", headers=auth_headers, json={
        "employee_id": employee["id"], "work": original,
    })
    assert scanned.status_code == 201, scanned.text
    assert scanned.json()["scan_uid"] == uid
    assert float(scanned.json()["total_amount"]) == 3000
    assert (scanned.json()["production_no"], scanned.json()["sales_order_no"]) == (NEW_PO, NEW_SO)
    duplicate = client.post("/api/payroll/scan/numeric-work", headers=auth_headers, json={"token": token, "employee_id": employee["id"]})
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["record"]["id"] == scanned.json()["id"]
    assert duplicate.json()["record"]["duplicate"] is True
    assert duplicate.json()["work"]["production_no"] == NEW_PO
    for reference in (OLD_PO, NEW_PO, OLD_SO, NEW_SO):
        for parameter in ("order_no", "search"):
            result = client.get("/api/payroll/qr-labels", headers=auth_headers, params={parameter: reference})
            assert result.status_code == 200, result.text
            assert result.json()["total"] == 1
        report = client.get("/api/payroll/reports/order-qr-status", headers=auth_headers, params={"order_no": reference})
        assert report.status_code == 200, report.text
        assert report.json()["order_no"] == (NEW_PO if reference.startswith("PO-") else NEW_SO)


def test_payroll_snapshot_translation_preserves_unknown_and_tampered_fields(client, auth_headers):
    po, so = _orders()
    source = {"production_order_id": po, "sales_order_id": so, "production_no": OLD_PO,
              "sales_order_no": OLD_SO, "label_id": OLD_PO, "operation_name": OLD_SO,
              "quantity": 12, "rate_per_piece": 250, "notes": OLD_PO}
    with TestSessionLocal() as db:
        expected = {**source, "production_no": NEW_PO, "sales_order_no": NEW_SO}
        assert _canonical_payroll_snapshot(db, source) == expected
        assert json.loads(_canonical_payroll_snapshot(db, json.dumps(source))) == expected
        tampered = {**source, "production_no": "PO-UNRELATED", "rate_per_piece": 999}
        result = _canonical_payroll_snapshot(db, tampered)
        assert result["production_no"] == "PO-UNRELATED"
        assert result["rate_per_piece"] == 999
        assert result != expected
        plain = ' {"notes": "PO-2026-000606"} '
        assert _canonical_payroll_snapshot(db, plain) == plain


def test_legacy_no_uid_retry_uses_original_hash_after_reference_migration(client, auth_headers):
    po, so = _orders(canonical=False)
    employee = _create_employee(client, auth_headers)
    payload = {"employee_id": employee["id"], "production_no": OLD_PO, "sales_order_no": OLD_SO,
               "scanned_at": datetime.now(timezone.utc).isoformat(), "quantity": 10, "rate_per_piece": 250,
               "operation_section": "sewing", "operation_name": "Legacy operation"}
    created = client.post("/api/payroll/records", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    with TestSessionLocal() as db:
        record = db.get(PayrollRecord, created.json()["id"])
        original_hash = record.dedupe_key
        db.get(ProductionOrder, po).production_no = NEW_PO
        db.get(SalesOrder, so).order_no = NEW_SO
        db.add_all([
            BusinessOrderAlias(namespace="PO", entity_id=po, reference=OLD_PO, canonical_reference=NEW_PO),
            BusinessOrderAlias(namespace="SO", entity_id=so, reference=OLD_SO, canonical_reference=NEW_SO),
        ])
        record.production_no, record.sales_order_no = NEW_PO, NEW_SO
        db.commit()
    for request in (payload, {**payload, "production_no": NEW_PO, "sales_order_no": NEW_SO}):
        replay = client.post("/api/payroll/records", headers=auth_headers, json=request)
        assert replay.status_code == 201, replay.text
        assert replay.json()["duplicate"] is True
        assert replay.json()["id"] == created.json()["id"]
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).count() == 1
        assert db.get(PayrollRecord, created.json()["id"]).dedupe_key == original_hash


def test_alias_reference_only_qr_cannot_bypass_production_factory_scope(client, auth_headers):
    _orders()
    employee = _create_employee(client, auth_headers)
    foreign = _create_user_with_permissions(client, auth_headers, email=f"alias-scan-{uuid4().hex}@example.com",
                                             permissions=["payroll.scan"], factory_code="BST")
    denied = client.post("/api/payroll/records", headers=foreign, json={
        "employee_id": employee["id"], "production_no": OLD_PO, "quantity": 10, "rate_per_piece": 250,
    })
    assert denied.status_code == 404, denied.text
    assert "Production order" in denied.json()["detail"]


def test_standalone_factory_so_alias_reprints_as_actual_po_with_null_sales_snapshot(client, auth_headers):
    po, _ = _orders()
    old_public = "SO-2026-000606"
    with TestSessionLocal() as db:
        db.get(ProductionOrder, po).sales_order_id = None
        db.add(BusinessOrderAlias(namespace="PUBLIC_PO", entity_id=po, reference=old_public, canonical_reference=NEW_PO))
        db.commit()
    uid = f"PY:{uuid4().hex}"
    payload = _compact(po, "-", uid).replace(OLD_SO, old_public)
    issued = client.post("/api/payroll/qr-labels/issue", headers=auth_headers, json={"labels": [{
        "label_uid": uid, "payload": payload, "production_order_id": po, "production_no": OLD_PO,
        "sales_order_no": None, "operation_section": "sewing", "operation_name": "Sewing",
        "quantity": 12, "rate_per_piece": 250,
    }]})
    assert issued.status_code == 200, issued.text
    for field in ("order_no", "search"):
        result = client.get("/api/payroll/qr-labels", params={field: old_public}, headers=auth_headers)
        assert result.status_code == 200, result.text
        assert result.json()["total"] == 1
        row = result.json()["items"][0]
        assert row["production_no"] == NEW_PO
        assert row["payload"].split("*")[15] == NEW_PO
    report = client.get("/api/payroll/reports/order-qr-status", params={"order_no": old_public}, headers=auth_headers)
    assert report.status_code == 200, report.text
    assert report.json()["order_no"] == NEW_PO


def test_real_sales_and_public_alias_collision_requires_production_identity(client, auth_headers):
    po, so = _orders()
    with TestSessionLocal() as db:
        db.get(ProductionOrder, po).sales_order_id = None
        db.add(BusinessOrderAlias(namespace="PUBLIC_PO", entity_id=po, reference=NEW_SO, canonical_reference=NEW_PO))
        db.commit()
        with pytest.raises(HTTPException) as error:
            canonical_order_reference(db, "SO", NEW_SO)
        assert error.value.status_code == 409
        assert canonical_order_reference(db, "SO", NEW_SO, production_order_id=po) == NEW_PO
        assert canonical_order_reference(db, "SO", NEW_SO, entity_id=so) == NEW_SO
        source = {"production_order_id": po, "sales_order_no": NEW_SO, "rate_per_piece": 250, "label_id": NEW_SO}
        assert _canonical_payroll_snapshot(db, source) == {**source, "sales_order_no": NEW_PO}

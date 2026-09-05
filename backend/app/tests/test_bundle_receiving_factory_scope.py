from itertools import permutations
from uuid import uuid4

import pytest

from app.models import (
    Bundle, BundleScanLog, Department, ModelBOM, ProductionBatch, ProductionOrder,
    SewingAssignment, SewingFlow, User, WorkOrder,
)
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_user_with_permissions


FACTORIES = ("MIL", "BST", "ECO")


def _ready_bundle(factory, status="sent_to_sewing"):
    with TestSessionLocal() as db:
        db.query(ModelBOM).filter(ModelBOM.model_id == 1).delete(synchronize_session=False)
        po = ProductionOrder(
            production_no=f"SCOPE-{uuid4().hex}", production_type="branded_stock",
            model_id=1, planned_quantity=10, status="new",
        )
        db.add(po)
        db.flush()
        target = db.query(Department).filter(Department.code == factory).one()
        cutting = db.query(Department).filter(Department.code == "CUT").one()
        wo = WorkOrder(
            production_order_id=po.id, department_id=target.id, operation="sewing",
            status="waiting", planned_input_qty=10, planned_output_qty=10,
        )
        bundle = Bundle(
            bundle_no=f"SCOPE-{uuid4().hex}", barcode=uuid4().hex,
            production_order_id=po.id, model_id=1, color="white", size="M", quantity=10,
            sewing_factory_code=factory, status=status,
            current_department_id=cutting.id, next_department_id=target.id,
        )
        db.add_all([wo, bundle])
        db.commit()
        return bundle.id, wo.id, po.id, target.id


def _headers(client, auth_headers, factory, permissions=None):
    return _create_user_with_permissions(
        client, auth_headers, email=f"bundle-scope-{uuid4().hex}@example.com",
        permissions=permissions if permissions is not None else ["sewing.bundles"],
        factory_code=factory,
    )


def _assert_unreceived(bundle_id, work_order_id, status):
    with TestSessionLocal() as db:
        bundle = db.get(Bundle, bundle_id)
        assert bundle.status == status
        assert bundle.current_department_id != bundle.next_department_id
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id == bundle_id).count() == 0
        wo = db.get(WorkOrder, work_order_id)
        assert wo.status == "waiting"
        assert wo.actual_input_qty == 0


@pytest.mark.parametrize("session_factory,bundle_factory", list(permutations(FACTORIES, 2)))
@pytest.mark.parametrize("status", ["created", "sent_to_sewing"])
def test_scan_rejects_other_factory_without_query_scope(client, auth_headers, session_factory, bundle_factory, status):
    bundle_id, wo_id, _, _ = _ready_bundle(bundle_factory, status)
    headers = _headers(client, auth_headers, session_factory)
    response = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=headers)
    assert response.status_code == 403, response.text
    _assert_unreceived(bundle_id, wo_id, status)


@pytest.mark.parametrize("factory", FACTORIES)
@pytest.mark.parametrize("method", ["created_scan", "sent_scan", "manual"])
def test_same_factory_receiving_preserves_handoff(client, auth_headers, factory, method):
    status = "created" if method == "created_scan" else "sent_to_sewing"
    bundle_id, wo_id, po_id, target_id = _ready_bundle(factory, status)
    headers = _headers(client, auth_headers, factory)
    if method == "manual":
        response = client.post("/api/bundles/manual-receive-sewing", headers=headers, json={
            "production_order_id": po_id, "factory_code": factory,
        })
    else:
        response = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=headers)
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        bundle = db.get(Bundle, bundle_id)
        assert bundle.status == "received_sewing"
        assert bundle.sewing_factory_code == factory
        assert bundle.current_department_id == target_id
        wo = db.get(WorkOrder, wo_id)
        assert wo.status == "in_progress"
        assert wo.actual_input_qty == 10
        scan = db.query(BundleScanLog).filter(BundleScanLog.bundle_id == bundle_id).one()
        assert scan.scan_type == "received_sewing"
        assert scan.to_department_id == target_id
        assert scan.scanned_by is not None
    duplicate = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=headers)
    assert duplicate.status_code == 409, duplicate.text


def test_query_cannot_disguise_eco_bundle_as_milana(client, auth_headers):
    bundle_id, wo_id, _, _ = _ready_bundle("ECO")
    headers = _headers(client, auth_headers, "MIL")
    response = client.post(f"/api/bundles/{bundle_id}/receive-sewing?factory=MIL", headers=headers)
    assert response.status_code == 403, response.text
    _assert_unreceived(bundle_id, wo_id, "sent_to_sewing")


def test_admin_must_select_bundle_factory(client, auth_headers):
    bundle_id, wo_id, _, _ = _ready_bundle("ECO")
    response = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=auth_headers)
    assert response.status_code == 403, response.text
    _assert_unreceived(bundle_id, wo_id, "sent_to_sewing")
    login = client.post("/api/auth/login-json", json={
        "email": "admin@example.com", "password": "test-admin-password-123!", "factory_code": "ECO",
    })
    assert login.status_code == 200, login.text
    response = client.post(f"/api/bundles/{bundle_id}/receive-sewing")
    assert response.status_code == 200, response.text


def test_factory_membership_does_not_replace_sewing_permission(client, auth_headers):
    bundle_id, wo_id, _, _ = _ready_bundle("ECO")
    headers = _headers(client, auth_headers, "ECO", permissions=["planning.view"])
    response = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=headers)
    assert response.status_code == 403, response.text
    _assert_unreceived(bundle_id, wo_id, "sent_to_sewing")


def test_secondary_factory_permission_requires_switching_session(client, auth_headers):
    bundle_id, wo_id, _, _ = _ready_bundle("ECO")
    headers = _headers(client, auth_headers, "MIL")
    me = client.get("/api/auth/me", headers=headers).json()
    with TestSessionLocal() as db:
        user = db.get(User, me["id"])
        user.extra_permissions = ["factory:ECO:sewing.bundles"]
        db.commit()
    response = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=headers)
    assert response.status_code == 403, response.text
    _assert_unreceived(bundle_id, wo_id, "sent_to_sewing")
    login = client.post("/api/auth/login-json", json={
        "email": me["email"], "password": "PayrollTest123!", "factory_code": "ECO",
    })
    assert login.status_code == 200, login.text
    response = client.post(f"/api/bundles/{bundle_id}/receive-sewing")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("requested_factory", [None, "ECO"])
def test_manual_receive_cannot_take_eco_bundles_in_milana(client, auth_headers, requested_factory):
    bundle_id, wo_id, po_id, _ = _ready_bundle("ECO")
    response = client.post("/api/bundles/manual-receive-sewing", headers=_headers(client, auth_headers, "MIL"), json={
        "production_order_id": po_id, "factory_code": requested_factory,
    })
    assert response.status_code == (403 if requested_factory else 404), response.text
    _assert_unreceived(bundle_id, wo_id, "sent_to_sewing")


@pytest.mark.parametrize("session_factory,line_factory,expected", [("MIL", "ECO", 403), ("MIL", "MIL", 409), ("ECO", "ECO", 200)])
def test_batch_acceptance_respects_factory_and_preserves_assignment(client, auth_headers, session_factory, line_factory, expected):
    bundle_id, wo_id, po_id, target_id = _ready_bundle("ECO")
    with TestSessionLocal() as db:
        batch = ProductionBatch(production_order_id=po_id, batch_no="SCOPE-1", planned_quantity=10)
        flow = SewingFlow(code=f"SCOPE-{uuid4().hex[:8]}", name="Scope test line", factory_code=line_factory, is_active=True)
        db.add_all([batch, flow])
        db.flush()
        db.get(Bundle, bundle_id).production_batch_id = batch.id
        db.get(WorkOrder, wo_id).production_batch_id = batch.id
        db.commit()
        batch_id, flow_id = batch.id, flow.id
    response = client.post(
        f"/api/bundles/sewing-batches/{batch_id}/accept",
        headers=_headers(client, auth_headers, session_factory), json={"sewing_flow_id": flow_id},
    )
    assert response.status_code == expected, response.text
    with TestSessionLocal() as db:
        assignments = db.query(SewingAssignment).filter(SewingAssignment.work_order_id == wo_id).all()
        if expected == 200:
            assert len(assignments) == 1
            assert assignments[0].quantity == 10
            assert assignments[0].sewing_flow_id == flow_id
            assert db.get(Bundle, bundle_id).current_department_id == target_id
            assert db.get(WorkOrder, wo_id).actual_input_qty == 10
        else:
            assert not assignments
            _assert_unreceived(bundle_id, wo_id, "sent_to_sewing")

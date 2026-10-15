from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import FinishedGoodsStock, Package, PackagePrintRun, PackagePrintRunMember
from app.tests.test_package_workflows import packaging_order, warehouse, create_run, package_qr  # noqa: F401
from app.tests.test_payroll import _create_user_with_permissions


@pytest.mark.parametrize("received", [False, True])
def test_operator_edits_printed_package_without_approval(client, auth_headers, warehouse, packaging_order, received):
    run = create_run(client, auth_headers, packaging_order, 2)
    pid, sibling = run["package_ids"]
    old_qr = package_qr(pid)
    if received:
        assert client.post("/api/packages/print-runs/receive", headers=warehouse, json={"code": run["code"]}).status_code == 200
    operator = _create_user_with_permissions(client, auth_headers, email=f"pack-{uuid4().hex}@example.com", permissions=["packaging.packages"])
    result = client.post(f"/api/packages/{pid}/change-requests", headers=operator,
                         json={"request_type": "edit", "payload": {"weight_kg": 2.5}})
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "approved"
    with SessionLocal() as db:
        assert db.get(PackagePrintRun, run["id"]).superseded_at is not None
        assert db.query(PackagePrintRunMember).filter_by(run_id=run["id"], package_id=pid).one().snapshot["weight_kg"] == 1.5
        assert float(db.get(Package, sibling).weight_kg) == 1.5
    old = client.post("/api/packages/print-runs/receive", headers=warehouse, json={"code": old_qr})
    assert old.status_code in {404, 409}, old.text
    if not received:
        new = client.post("/api/packages/print-runs/receive", headers=warehouse, json={"code": package_qr(pid)})
        assert new.status_code == 200, new.text


def test_operator_deletes_one_printed_package_and_remaining_run_receives(client, auth_headers, warehouse, packaging_order):
    run = create_run(client, auth_headers, packaging_order, 2)
    pid, sibling = run["package_ids"]
    operator = _create_user_with_permissions(client, auth_headers, email=f"pack-{uuid4().hex}@example.com", permissions=["packaging.packages"])
    result = client.post(f"/api/packages/{pid}/change-requests", headers=operator, json={"request_type": "delete"})
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "approved"
    with SessionLocal() as db:
        assert db.get(Package, pid) is None
        assert db.get(Package, sibling) is not None
        assert db.query(PackagePrintRunMember).filter_by(run_id=run["id"]).count() == 2
    received = client.post("/api/packages/print-runs/receive", headers=warehouse, json={"code": package_qr(sibling)})
    assert received.status_code == 200, received.text


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_direct_correction_preserves_reserved_stock(client, auth_headers, packaging_order, action):
    run = create_run(client, auth_headers, packaging_order, 1)
    pid = run["package_ids"][0]
    with SessionLocal() as db:
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        stock.reserved_qty = 1
        stock.available_qty -= 1
        db.commit()
    result = client.post(f"/api/packages/{pid}/change-requests", headers=auth_headers,
                         json={"request_type": action, "payload": {"weight_kg": 2.5}})
    assert result.status_code == 409, result.text
    with SessionLocal() as db:
        assert db.get(Package, pid) is not None
        assert db.get(PackagePrintRun, run["id"]).superseded_at is None


def test_delete_then_edit_then_delete_retains_all_historical_labels(client, auth_headers, packaging_order):
    run = create_run(client, auth_headers, packaging_order, 2)
    first, second = run["package_ids"]
    for pid, payload in [(first, {"request_type": "delete"}),
                         (second, {"request_type": "edit", "payload": {"weight_kg": 2.5}}),
                         (second, {"request_type": "delete"})]:
        response = client.post(f"/api/packages/{pid}/change-requests", headers=auth_headers, json=payload)
        assert response.status_code == 201, response.text
    with SessionLocal() as db:
        assert db.get(Package, first) is None and db.get(Package, second) is None
        for member in db.query(PackagePrintRunMember).filter(PackagePrintRunMember.package_id.in_([first, second])):
            parent = db.get(PackagePrintRun, member.run_id)
            assert parent.deleted_at or member.package_id in parent.deleted_package_ids

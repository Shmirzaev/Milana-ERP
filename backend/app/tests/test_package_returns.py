from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import Package, PackagePrintRun, PackagePrintRunMember, FinishedGoodsStock
from app.tests.test_package_workflows import packaging_order, warehouse, create_run, package_qr, stock_fingerprint  # noqa: F401


def test_return_correct_reprint_receive_preserves_history_and_rejects_old_qr(client, auth_headers, warehouse, packaging_order):
    run = create_run(client, auth_headers, packaging_order, 2)
    ids = run["package_ids"]
    old_qrs = [package_qr(pid) for pid in ids]
    before = stock_fingerprint()
    pending = client.get("/api/packages/receiving-options?q=PO-PRINT", headers=warehouse)
    assert pending.status_code == 200, pending.text
    assert pending.json()["rows"][0]["package_ids"] == ids
    returned = client.post("/api/packages/return-to-packaging", headers=warehouse, json={"package_ids": ids, "reason": "Wrong weight on labels"})
    assert returned.status_code == 200, returned.text
    assert stock_fingerprint() == before
    with SessionLocal() as db:
        stock_ids = [row.id for row in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids))]
    assert not set(stock_ids).intersection(row["id"] for row in client.get("/api/finished-goods", headers=warehouse).json())
    reserved = client.post("/api/finished-goods/reserve", headers=auth_headers,
                           params={"stock_id": stock_ids[0], "quantity": 1, "sales_order_id": 1})
    assert reserved.status_code == 409 and "awaiting correction" in reserved.text
    assert stock_fingerprint() == before
    assert client.post("/api/packages/print-runs/receive", headers=warehouse, json={"code": run["code"]}).status_code == 409
    assert client.get(f"/api/packages/{ids[0]}/label", headers=auth_headers).status_code == 409
    assert client.get("/api/packages/receiving-options", headers=warehouse).json()["rows"] == []
    listing = client.get("/api/packages?status=returned_to_packaging", headers=auth_headers).json()
    assert all(p["return_reason"] == "Wrong weight on labels" for p in listing)
    assert {p["id"] for p in listing} == set(ids)
    for pid in ids:
        corrected = client.post(f"/api/packages/{pid}/correct-return", headers=auth_headers, json={"request_type": "edit", "payload": {"weight_kg": 2.5}})
        assert corrected.status_code == 200, corrected.text
    body = {"request_key": str(uuid4()), "package_ids": ids}
    resend = client.post("/api/packages/resend-corrected", headers=auth_headers, json=body)
    assert resend.status_code == 200, resend.text
    revised = resend.json()
    assert revised["id"] != run["id"]
    assert client.post("/api/packages/resend-corrected", headers=auth_headers, json=body).json() == revised
    for qr in old_qrs:
        assert client.post("/api/packages/print-runs/receive", headers=warehouse, json={"code": qr}).status_code == 409
        assert client.get(f"/api/packages/barcode/{qr}", headers=warehouse).status_code == 409
    assert client.get(f"/api/packages/print-runs/{revised['id']}/label", headers=auth_headers).status_code == 200
    received = client.post("/api/packages/print-runs/receive", headers=warehouse, json={"code": package_qr(ids[0])})
    assert received.status_code == 200, received.text
    with SessionLocal() as db:
        assert db.get(PackagePrintRun, run["id"]).return_reason == "Wrong weight on labels"
        snapshots = db.query(PackagePrintRunMember).filter_by(run_id=run["id"]).all()
        assert all(member.snapshot["weight_kg"] == 1.5 for member in snapshots)
        assert db.query(PackagePrintRunMember).count() == 4
        assert all(db.get(Package, pid).status == "received_in_storage" for pid in ids)
        assert sum(s.quantity for s in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids))) == 4


@pytest.mark.parametrize("condition", ["partial", "received", "reserved", "permission"])
def test_return_rejects_unsafe_state_without_partial_changes(client, auth_headers, warehouse, packaging_order, condition):
    run = create_run(client, auth_headers, packaging_order, 2)
    ids = run["package_ids"]
    headers = warehouse
    if condition == "received":
        assert client.post("/api/packages/print-runs/receive", headers=warehouse, json={"code": run["code"]}).status_code == 200
    if condition == "reserved":
        with SessionLocal() as db:
            stock = db.query(FinishedGoodsStock).filter_by(package_id=ids[1]).one()
            stock.reserved_qty = 1; stock.available_qty -= 1; db.commit()
    if condition == "permission":
        from app.tests.test_payroll import _create_user_with_permissions
        headers = _create_user_with_permissions(client, auth_headers, email=f"return-{uuid4().hex}@example.com", permissions=["packaging.packages"])
    before = stock_fingerprint()
    result = client.post("/api/packages/return-to-packaging", headers=headers, json={"package_ids": ids[:1] if condition == "partial" else ids, "reason": "Incorrect label"})
    assert result.status_code in {403, 409}, result.text
    assert stock_fingerprint() == before
    with SessionLocal() as db:
        assert db.get(PackagePrintRun, run["id"]).returned_at is None
        assert all(db.get(Package, pid).status != "returned_to_packaging" for pid in ids)


def test_return_correction_permissions_and_quantity_budget(client, auth_headers, warehouse, packaging_order):
    run = create_run(client, auth_headers, packaging_order, 1)
    pid = run["package_ids"][0]
    assert client.post("/api/packages/return-to-packaging", headers=warehouse, json={"package_ids": [pid], "reason": "Wrong details"}).status_code == 200
    payload = {"request_type": "edit", "payload": {"weight_kg": 2}}
    assert client.post(f"/api/packages/{pid}/correct-return", headers=warehouse, json=payload).status_code == 403
    payload["payload"]["items"] = [{**packaging_order["items"][0], "quantity": 30}]
    rejected = client.post(f"/api/packages/{pid}/correct-return", headers=auth_headers, json=payload)
    assert rejected.status_code == 400 and "exceeds available packed quantity" in rejected.text
    resend = client.post("/api/packages/resend-corrected", headers=auth_headers, json={"request_key": str(uuid4()), "package_ids": [pid]})
    assert resend.status_code == 409

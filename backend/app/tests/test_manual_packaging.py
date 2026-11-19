"""Manual pack creation, immutable labels, separate warehouse receipt and recovery."""
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.schemas import AuditLog, FinishedGoodsStock, ManualPackageReceipt, Model, Package, PackagePrintRun, ProductionOrder, User
from app.tests.test_package_workflows import package_qr

PATH = "/api/packages/manual-packaging"


def login(client, email, factory="MIL"):
    with SessionLocal() as db:
        db.query(User).filter_by(email=email).one().factory_code = factory
        db.commit()
    result = client.post("/api/auth/token", data={"username": email, "password": "demo12345"})
    assert result.status_code == 200
    headers = {"Authorization": "Bearer " + result.json()["access_token"]}
    if factory != "MIL":
        switched = client.post("/api/auth/switch-factory", json={"factory_code": factory}, headers=headers)
        assert switched.status_code == 200
        return {}
    return headers


def body(**overrides):
    with SessionLocal() as db:
        model = db.query(Model).filter_by(code="T-SHIRT-001").one()
        return {"request_key": str(uuid4()), "model_id": model.id, "color": "White",
                "weight_kg": 1.25, "count": 2, "pack_quantities": [8, 3],
                "packaging_department_code": "PKG", **overrides}


def counts():
    with SessionLocal() as db:
        return tuple(db.query(table).count() for table in (Package, PackagePrintRun, ManualPackageReceipt, FinishedGoodsStock, ProductionOrder, AuditLog))


def test_manual_pack_label_and_warehouse_handoff(client):
    packaging = login(client, "packaging@example.com")
    warehouse = login(client, "fgs@example.com")
    payload = body()
    before = counts()
    response = client.post(PATH, json=payload, headers=packaging)
    assert response.status_code == 201, response.text
    saved = response.json()
    run = saved["print_run"]
    assert run["count"] == 2 and run["quantity"] == 11 and run["received_at"] is None
    listed = client.get("/api/packages?include_total=true&packaging_department_code=PKG", headers=packaging).json()["rows"]
    assert {row["print_run_id"] for row in listed} == {run["id"]}
    assert all(row["manual_source"]["receipt_no"] == saved["receipt_no"]
               and row["manual_source"]["evidence"]["source"] == "manual_packaging"
               and row["model_code"] == "T-SHIRT-001" for row in listed)
    assert client.post(PATH, json=payload, headers=packaging).json() == saved
    assert counts()[4] == before[4], "manual packs must not invent a production order"
    with SessionLocal() as db:
        packs = db.query(Package).filter(Package.id.in_(run["package_ids"])).order_by(Package.id).all()
        assert [p.total_quantity for p in packs] == [8, 3]
        assert all(p.status == "packed" and p.received_at is None and p.received_by is None for p in packs)
        assert all(p.production_order_id is None and p.packaging_department_code == "PKG" for p in packs)
        receipt = db.get(ManualPackageReceipt, packs[0].manual_receipt_id)
        assert receipt.evidence["source"] == "manual_packaging"
    snapshot = counts()
    for _ in range(2):
        label = client.get(f"/api/packages/print-runs/{run['id']}/label", headers=packaging)
        assert label.status_code == 200 and "PKG-" in label.text
    assert counts() == snapshot, "reprinting must not create more packs/stock/audits"
    shipment = client.post("/api/shipments", json={"notes": "Manual pack handoff"}, headers=warehouse)
    assert shipment.status_code == 201
    scan = client.post(f"/api/shipments/{shipment.json()['id']}/scan-package",
                       json={"code": package_qr(run["package_ids"][0])}, headers=warehouse)
    assert scan.status_code == 200 and scan.json()["ok"] is False, scan.text
    for _ in range(2):
        received = client.post("/api/packages/print-runs/receive", json={"code": package_qr(run["package_ids"][0])}, headers=warehouse)
        assert received.status_code == 200, received.text
    with SessionLocal() as db:
        assert all(db.get(Package, pid).status == "received_in_storage" for pid in run["package_ids"])
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(run["package_ids"])).count() == 2


@pytest.mark.parametrize("email,factory,department", [
    ("packaging@example.com", "MIL", "PKG"),
    ("besttex.packaging@example.com", "BST", "BPK"),
    ("eco.cotton.packaging@example.com", "ECO", "ECP"),
])
def test_factory_creation_and_cross_factory_refusal(client, email, factory, department):
    headers = login(client, email, factory)
    payload = body(packaging_department_code=department)
    response = client.post(PATH, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        assert all(db.get(Package, pid).packaging_department_code == department for pid in response.json()["print_run"]["package_ids"])
    before = counts()
    response = client.post(PATH, json=body(packaging_department_code="ECP" if department != "ECP" else "PKG"), headers=headers)
    assert response.status_code == 403, response.text
    assert counts() == before


@pytest.mark.parametrize("change", [
    {"pack_quantities": [0, 2]}, {"pack_quantities": [True, 2]},
    {"pack_quantities": [10001, 3]}, {"count": 3}, {"color": "  "},
    {"weight_kg": 0}, {"warehouse_id": 1}, {"storage_cell": "A-01"},
    {"packaging_department_code": "OTHER"}, {"model_id": 2147483647},
])
def test_invalid_input_leaves_no_business_writes(client, change):
    headers = login(client, "packaging@example.com")
    before = counts()
    response = client.post(PATH, json=body(**change), headers=headers)
    assert response.status_code in {400, 422}, response.text
    assert counts() == before


def test_permission_denied_and_changed_retry(client):
    warehouse = login(client, "fgs@example.com")
    before = counts()
    assert client.post(PATH, json=body(), headers=warehouse).status_code == 403
    assert counts() == before
    headers = login(client, "packaging@example.com")
    payload = body()
    assert client.post(PATH, json=payload, headers=headers).status_code == 201
    before = counts()
    assert client.post(PATH, json={**payload, "color": "Blue"}, headers=headers).status_code == 409
    assert counts() == before


def test_recovery_and_cancel_preserve_request_identity(client):
    headers = login(client, "packaging@example.com")
    payload = body()
    saved = client.post(PATH, json=payload, headers=headers).json()
    result = client.post(PATH + "/reconcile", json=payload, headers=headers)
    assert result.json() == {"status": "completed", "result": saved}
    new = body()
    assert client.post(PATH + "/reconcile", json=new, headers=headers).json() == {"status": "cancelled"}
    before = counts()
    assert client.post(PATH, json=new, headers=headers).status_code == 409
    assert counts() == before


def test_failure_rolls_back_all_packs_stock_audit_then_retry(client, monkeypatch):
    from app.models.packaging import manual_packages_service as service
    headers = login(client, "packaging@example.com")
    payload = body()
    original = service.insert_manual_package
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("injected second-pack persistence failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "insert_manual_package", fail_second)
    before = counts()
    with pytest.raises(RuntimeError, match="second-pack"):
        client.post(PATH, json=payload, headers=headers)
    assert counts() == before
    monkeypatch.setattr(service, "insert_manual_package", original)
    assert client.post(PATH, json=payload, headers=headers).status_code == 201


def test_cancel_mistaken_unreceived_packs_retires_labels_and_prevents_retry(client):
    headers = login(client, "packaging@example.com")
    payload = body()
    saved = client.post(PATH, json=payload, headers=headers).json()
    run = saved["print_run"]
    response = client.delete(f"{PATH}/{run['id']}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["deleted_count"] == 2
    with SessionLocal() as db:
        assert db.query(Package).filter(Package.id.in_(run["package_ids"])).count() == 0
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(run["package_ids"])).count() == 0
        assert db.get(PackagePrintRun, run["id"]).deleted_at is not None
        assert db.query(ManualPackageReceipt).count() == 1, "source evidence stays immutable"
    assert client.get(f"/api/packages/print-runs/{run['id']}/label", headers=headers).status_code == 410
    assert client.post(PATH, json=payload, headers=headers).status_code == 410
    assert client.post(PATH + "/reconcile", json=payload, headers=headers).json() == {"status": "completed_unavailable"}
    fresh = client.post(PATH, json=body(), headers=headers).json()
    assert not set(fresh["print_run"]["package_ids"]) & set(run["package_ids"])
    assert fresh["print_run"]["run_no"] != run["run_no"]
    assert not {p["package_no"] for p in fresh["print_run"]["packages"]} & {p["package_no"] for p in run["packages"]}


def test_cancel_refuses_received_and_cross_factory_packs(client):
    headers = login(client, "packaging@example.com")
    saved = client.post(PATH, json=body(), headers=headers).json()
    rid = saved["print_run"]["id"]
    other = login(client, "besttex.packaging@example.com", "BST")
    assert client.delete(f"{PATH}/{rid}", headers=other).status_code == 403
    warehouse = login(client, "fgs@example.com")
    assert client.post("/api/packages/print-runs/receive", json={"code": package_qr(saved["print_run"]["package_ids"][0])}, headers=warehouse).status_code == 200
    before = counts()
    assert client.delete(f"{PATH}/{rid}", headers=headers).status_code == 409
    assert counts() == before

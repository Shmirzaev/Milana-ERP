"""Exact operator-confirmed batch x model/color/size evidence at every write seam."""
from uuid import uuid4

import pytest

from app.schemas import Package, PackageBatchAllocation, PackagePrintRunMember, ProductionOrderItem, SewingRecord
from app.tests.conftest import TestSessionLocal
from app.tests.test_direct_packaging import PATH, body, package, seed, sources
from app.models.packaging.allocation_items_service import normalize_matrix


def matrix_facts():
    facts = seed(scenario="legacy_later")
    with TestSessionLocal.begin() as db:
        rows = db.query(SewingRecord).filter_by(work_order_id=facts["sewing_work_order_id"]).order_by(
            SewingRecord.production_batch_id).all()
        rows[0].size_quantities = [{"size": "M", "quantity": 50}, {"size": "L", "quantity": 30}]
        rows[1].size_quantities = [{"size": "M", "quantity": 20}, {"size": "L", "quantity": 50}]
        db.add(ProductionOrderItem(production_order_id=facts["order_id"], model_id=facts["model_id"],
                                  color="white", size="L", planned_quantity=80))
    return facts


def item(facts, size, quantity):
    return {"model_id": facts["model_id"], "color": "white", "size": size, "quantity": quantity}


def mixed(facts):
    first, second, _ = facts["batch_ids"]
    return package(facts, batch_id=None, items=[item(facts, "M", 30), item(facts, "L", 30)], batch_allocations=[
        {"production_batch_id": first, "quantity": 35,
         "item_breakdown": [item(facts, "M", 25), item(facts, "L", 10)]},
        {"production_batch_id": second, "quantity": 25,
         "item_breakdown": [item(facts, "M", 5), item(facts, "L", 20)]}])


@pytest.mark.parametrize("path", ["/api/packages", "/api/packages/bulk", PATH])
def test_every_create_path_requires_exact_mixed_attribution(client, auth_headers, path):
    facts = matrix_facts()
    row = mixed(facts)
    for allocation in row["batch_allocations"]:
        allocation.pop("item_breakdown")
    request = body(facts, [row]) if path == PATH else row
    response = client.post(path, headers=auth_headers, json=request)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "MIXED_PACKAGE_ITEM_BREAKDOWN_REQUIRED"
    with TestSessionLocal() as db:
        assert db.query(Package).filter_by(production_order_id=facts["order_id"]).count() == 0


def test_exact_matrix_survives_readback_print_receipt_and_grade_balance(client, auth_headers):
    facts = matrix_facts()
    request = body(facts, [mixed(facts)])
    response = client.post(PATH, headers=auth_headers, json=request)
    assert response.status_code == 201, response.text
    result = response.json()
    assert client.post(PATH, headers=auth_headers, json=request).json() == result
    allocations = result["packages"][0]["batch_allocations"]
    assert allocations == normalize_matrix(mixed(facts)["batch_allocations"], mixed(facts)["items"])
    with TestSessionLocal() as db:
        package_id = db.query(Package.id).filter_by(production_order_id=facts["order_id"]).scalar()
        snapshot = db.query(PackagePrintRunMember).filter_by(package_id=package_id).one().snapshot
        assert snapshot["batch_allocations"] == allocations
    detail = client.get(f"/api/packages/{package_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert all(row["item_breakdown"] and row["batch_no"] for row in detail.json()["batch_allocations"])
    label = client.get(f"/api/packages/print-runs/{result['id']}/label", headers=auth_headers)
    assert label.status_code == 200 and "M: 25" in label.text and "L: 20" in label.text
    balance = sources(client, facts, auth_headers)["items"][0]
    assert balance["actual_size_verified"]
    assert {row["size"]: row["remaining"] for row in balance["size_balances"]} == {"L": 20, "M": 25}
    grade = client.get(f"/api/packages/first-grade/balance/{facts['order_id']}", headers=auth_headers,
                       params={"production_batch_id": facts["batch_ids"][0]})
    assert grade.status_code == 200, grade.text
    assert {row["size"]: row["remaining"] for row in grade.json()["sizes"]} == {"L": 20, "M": 25}
    received = client.post("/api/packages/print-runs/receive", headers=auth_headers, json={"code": result["code"]})
    assert received.status_code == 200, received.text


@pytest.mark.parametrize("invalid", ["batch_total", "identity_total", "size_budget", "fractional", "negative", "boolean"])
def test_matrix_refusals_are_atomic(client, auth_headers, invalid):
    facts = matrix_facts()
    row = mixed(facts)
    cells = row["batch_allocations"][0]["item_breakdown"]
    if invalid == "batch_total":
        cells[0]["quantity"] = 26
    elif invalid == "identity_total":
        cells[0]["size"] = "XL"
    elif invalid == "size_budget":
        row["items"] = [item(facts, "M", 60)]
        row["batch_allocations"][0]["item_breakdown"] = [item(facts, "M", 35)]
        row["batch_allocations"][1]["item_breakdown"] = [item(facts, "M", 25)]
    else:
        cells[0]["quantity"] = {"fractional": 25.1, "negative": -25, "boolean": True}[invalid]
    response = client.post(PATH, headers=auth_headers, json=body(facts, [row]))
    assert response.status_code in {400, 409, 422}, response.text
    with TestSessionLocal() as db:
        assert db.query(Package).filter_by(production_order_id=facts["order_id"]).count() == 0


def test_metadata_correction_preserves_matrix_and_content_change_requires_replacement(client, auth_headers):
    facts = matrix_facts()
    created = client.post(PATH, headers=auth_headers, json=body(facts, [mixed(facts)]))
    assert created.status_code == 201, created.text
    package_id = created.json()["package_ids"][0]
    corrected = client.post(f"/api/packages/{package_id}/change-requests", headers=auth_headers,
                            json={"request_type": "edit", "reason": "Correct weight", "payload": {"weight_kg": 2}})
    assert corrected.status_code == 201, corrected.text
    with TestSessionLocal() as db:
        rows = db.query(PackageBatchAllocation).filter_by(package_id=package_id).order_by(
            PackageBatchAllocation.production_batch_id).all()
        assert [row.item_breakdown for row in rows] == [row["item_breakdown"] for row in normalize_matrix(mixed(facts)["batch_allocations"], mixed(facts)["items"])]
    refused = client.post(f"/api/packages/{package_id}/change-requests", headers=auth_headers,
                          json={"request_type": "edit", "reason": "Change actual sizes", "payload": {
                              "items": [item(facts, "M", 31), item(facts, "L", 29)]}})
    assert refused.status_code in {400, 409}, refused.text


def test_legacy_unknown_is_preserved_and_conservatively_reserves_each_possible_size(client, auth_headers):
    facts = matrix_facts()
    from app.schemas import PackageItem
    with TestSessionLocal.begin() as db:
        old = Package(package_no=f"OLD-{uuid4().hex}", barcode=uuid4().hex, production_order_id=facts["order_id"],
                      model_id=facts["model_id"], color="white", total_quantity=40, capacity=60, status="packed")
        old.items = [PackageItem(**item(facts, "M", 20)), PackageItem(**item(facts, "L", 20))]
        db.add(old); db.flush(); package_id = old.id
        db.add_all([PackageBatchAllocation(package_id=old.id, production_batch_id=batch, quantity=20)
                    for batch in facts["batch_ids"][:2]])
    state = sources(client, facts, auth_headers)["items"][1]
    assert {row["size"]: row["legacy_unknown_reserved_qty"] for row in state["size_balances"]} == {"L": 20, "M": 20}
    refused = client.post(PATH, headers=auth_headers, json=body(facts, [package(facts, 1, batch_id=facts["batch_ids"][1])]))
    assert refused.status_code == 409, refused.text
    printed = client.post("/api/packages/print-runs", headers=auth_headers,
                          json={"request_key": str(uuid4()), "package_ids": [package_id]})
    assert printed.status_code == 201, printed.text
    assert all("item_breakdown" not in row for row in printed.json()["packages"][0]["batch_allocations"])
    label = client.get(f"/api/packages/print-runs/{printed.json()['id']}/label", headers=auth_headers)
    assert label.status_code == 200 and "Sizes by batch unknown" in label.text
    corrected = client.post(f"/api/packages/{package_id}/change-requests", headers=auth_headers,
                            json={"request_type": "edit", "payload": {"notes": "History retained"}})
    assert corrected.status_code == 201, corrected.text
    with TestSessionLocal() as db:
        assert all(row.item_breakdown is None for row in db.query(PackageBatchAllocation).filter_by(package_id=package_id))


def test_missing_actual_sizes_keeps_operator_matrix_without_guessing_verification(client, auth_headers):
    facts = matrix_facts()
    with TestSessionLocal.begin() as db:
        for row in db.query(SewingRecord).filter_by(work_order_id=facts["sewing_work_order_id"]):
            row.size_quantities = []
    result = client.post(PATH, headers=auth_headers, json=body(facts, [mixed(facts)]))
    assert result.status_code == 201, result.text
    state = sources(client, facts, auth_headers)["items"][0]
    assert not state["actual_size_verified"]
    assert all(row["remaining"] is None and row["accepted"] is None for row in state["size_balances"])


@pytest.mark.parametrize("path", ["/api/packages", "/api/packages/bulk", PATH])
def test_pre_matrix_request_fingerprints_remain_replayable(client, auth_headers, path):
    from app.libs.dto.fulfillment.package_workflows import PrintRunCreatePackagesIn
    from app.libs.dto.packaging.tracking import PackageBulkIn, PackageIn
    from app.models.idempotency_service import request_fingerprint
    from app.schemas import IdempotencyRecord
    facts = matrix_facts()
    row = package(facts, 30)
    row["batch_allocations"] = [{"production_batch_id": facts["batch_ids"][0], "quantity": 30}]
    key = str(uuid4())
    if path == PATH:
        request = {"request_key": key, "packages": [row]}
        old_body = PrintRunCreatePackagesIn.model_validate(request).model_dump(mode="json")
        old_body.pop("work_order_id", None); old_body.pop("damaged_qty", None)
        old_body["packages"][0]["batch_allocations"][0].pop("item_breakdown", None)
    else:
        request = row
        dto = PackageBulkIn if path.endswith("bulk") else PackageIn
        old_body = dto.model_validate(row).model_dump(mode="json")
        old_body["batch_allocations"][0].pop("item_breakdown", None)
    request_headers = {**auth_headers, "Idempotency-Key": key}
    result = client.post(path, headers=request_headers, json=request)
    assert result.status_code in {200, 201}, result.text
    with TestSessionLocal() as db:
        receipt = db.query(IdempotencyRecord).filter_by(key=key).one()
        assert receipt.request_hash == request_fingerprint(old_body)
    assert client.post(path, headers=request_headers, json=request).json() == result.json()


def test_changed_returned_contents_require_and_preserve_explicit_replacement_matrix(client, auth_headers):
    facts = matrix_facts()
    created = client.post(PATH, headers=auth_headers, json=body(facts, [mixed(facts)])).json()
    package_id = created["package_ids"][0]
    returned = client.post("/api/packages/return-to-packaging", headers=auth_headers,
                           json={"package_ids": [package_id], "reason": "Check actual sources"})
    assert returned.status_code == 200, returned.text
    replacement = mixed(facts)
    replacement["batch_allocations"][0]["quantity"] = 34
    replacement["batch_allocations"][0]["item_breakdown"][0]["quantity"] = 24
    replacement["batch_allocations"][1]["quantity"] = 26
    replacement["batch_allocations"][1]["item_breakdown"][0]["quantity"] = 6
    corrected = client.post(f"/api/packages/{package_id}/correct-return", headers=auth_headers,
        json={"request_type": "edit", "reason": "Verified physical source split",
              "payload": {"batch_allocations": replacement["batch_allocations"]}})
    assert corrected.status_code == 200, corrected.text
    resent = client.post("/api/packages/resend-corrected", headers=auth_headers,
                         json={"request_key": str(uuid4()), "package_ids": [package_id]})
    assert resent.status_code == 200, resent.text
    assert resent.json()["packages"][0]["batch_allocations"] == normalize_matrix(
        replacement["batch_allocations"], replacement["items"])


def test_matrix_tampering_invalidates_the_printed_receiving_evidence(client, auth_headers):
    facts = matrix_facts()
    created = client.post(PATH, headers=auth_headers, json=body(facts, [mixed(facts)])).json()
    with TestSessionLocal.begin() as db:
        rows = db.query(PackageBatchAllocation).filter_by(package_id=created["package_ids"][0]).order_by(
            PackageBatchAllocation.production_batch_id).all()
        # Scalar totals and package contents remain unchanged; only the source
        # identity attribution changes, which must invalidate the old snapshot.
        rows[0].item_breakdown = [item(facts, "M", 24), item(facts, "L", 11)]
        rows[1].item_breakdown = [item(facts, "M", 6), item(facts, "L", 19)]
    result = client.post("/api/packages/print-runs/receive", headers=auth_headers, json={"code": created["code"]})
    assert result.status_code == 409, result.text


@pytest.mark.parametrize("exact", [False, True])
def test_shipment_quantity_review_preserves_exact_matrix_and_legacy_controls(client, auth_headers, exact):
    from app.schemas import Shipment, ShipmentPackage, ShipmentScanLog
    facts = matrix_facts()
    created = client.post(PATH, headers=auth_headers, json=body(facts, [mixed(facts)])).json()
    package_id = created["package_ids"][0]
    received = client.post("/api/packages/print-runs/receive", headers=auth_headers, json={"code": created["code"]})
    assert received.status_code == 200, received.text
    with TestSessionLocal.begin() as db:
        shipment = Shipment(shipment_no=uuid4().hex, status="created")
        db.add(shipment); db.flush(); shipment_id = shipment.id
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=package_id, quantity=60))
        db.add(ShipmentScanLog(shipment_id=shipment.id, package_id=package_id, scanned_code=uuid4().hex, scan_result="matched"))
        package_row = db.get(Package, package_id)
        if not exact:
            for allocation in package_row.batch_allocations:
                allocation.item_breakdown = None
        payload = {"expected_quantity": 60, "reason": "Verify physical quantity",
                   "items": [{"item_id": row.id, "quantity": row.quantity} for row in package_row.items]}
    path = f"/api/shipments/{shipment_id}/packages/{package_id}/quantity"
    assert client.post(path, headers=auth_headers, json=payload).status_code == 200
    payload["items"][0]["quantity"] -= 1
    result = client.post(path, headers=auth_headers, json=payload)
    assert result.status_code == (409 if exact else 200), result.text
    if exact:
        assert result.json()["detail"] == "MIXED_PACKAGE_QUANTITY_REQUIRES_PACKAGING_CORRECTION"
    with TestSessionLocal() as db:
        assert db.get(Package, package_id).total_quantity == (60 if exact else 59)


def test_old_pending_content_change_cannot_bypass_matrix_on_approval(client, auth_headers):
    from app.schemas import PackageChangeRequest
    facts = matrix_facts()
    created = client.post("/api/packages", headers=auth_headers, json=mixed(facts))
    assert created.status_code == 201, created.text
    package_id = created.json()["id"]
    with TestSessionLocal.begin() as db:
        package_row = db.get(Package, package_id)
        request = PackageChangeRequest(package_id=package_id, package_no=package_row.package_no,
            request_type="edit", status="pending", requested_by=1,
            payload_json={"items": [item(facts, "M", 31), item(facts, "L", 29)],
                "batch_allocations": [{"production_batch_id": allocation["production_batch_id"],
                                       "quantity": allocation["quantity"]} for allocation in mixed(facts)["batch_allocations"]]})
        db.add(request); db.flush(); request_id = request.id
    result = client.post(f"/api/packages/change-requests/{request_id}/approve", headers=auth_headers)
    assert result.status_code == 409, result.text
    with TestSessionLocal() as db:
        assert db.get(PackageChangeRequest, request_id).status == "pending"
        assert {row.size: row.quantity for row in db.get(Package, package_id).items} == {"M": 30, "L": 30}

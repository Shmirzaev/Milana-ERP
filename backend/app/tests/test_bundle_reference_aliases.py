from urllib.parse import quote

from app.core.order_reference import canonical_order_reference, order_reference_variants, resolve_order_id
from app.db.session import SessionLocal
from app.models import Bundle, PackagingReceipt, SewingRecord, WorkOrder
from app.models.order_reference import BusinessOrderAlias
from app.services.bundles import bundle_qr_payload
from app.tests.test_production_flow import _create_bundle_for_scan, _factory_headers


def _legacy_alias(bundle):
    old = f"BND-2026-{bundle['id']:06d}"
    with SessionLocal() as db:
        db.add(BusinessOrderAlias(namespace="BND", entity_id=bundle["id"], reference=old,
                                  canonical_reference=bundle["bundle_no"]))
        db.commit()
    return old


def test_bundle_alias_lookup_search_trace_and_print_return_current_number(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    old = _legacy_alias(bundle)
    current = bundle["bundle_no"]
    assert len(current) == 8 and current.startswith("BND-")
    with SessionLocal() as db:
        reservation = db.query(BusinessOrderAlias).filter_by(namespace="BND", reference=current).one()
        assert reservation.entity_id == bundle["id"]
        assert canonical_order_reference(db, "BND", old) == current
        assert resolve_order_id(db, "BND", old) == bundle["id"]
        assert {old, current} <= order_reference_variants(db, "BND", old)
        qr = bundle_qr_payload(db, db.get(Bundle, bundle["id"]))
    old_qr = qr.replace(f"BUNDLE:{current}", f"BUNDLE:{old}")
    for key in (old, current, old_qr, qr, bundle["barcode"]):
        for route in ("/api/bundles/lookup?code=", "/api/bundles/barcode/", "/api/barcode/bundle/"):
            response = client.get(route + quote(key, safe=""), headers=auth_headers)
            assert response.status_code == 200, response.text
            assert response.json()["bundle_no"] == current
        trace = client.get("/api/traceability/bundle/" + quote(key, safe=""), headers=auth_headers)
        assert trace.status_code == 200, trace.text
        assert any(row["bundle_no"] == current for row in trace.json()["bundles"])
    for key in (old, current):
        search = client.get("/api/search", params={"q": key}, headers=auth_headers)
        assert any(row["id"] == bundle["id"] and row["label"].startswith(current)
                   for row in search.json() if row["type"] == "Bundle")
        inventory = client.get("/api/bundles/cutting-inventory", params={"q": key}, headers=auth_headers)
        assert [row["id"] for row in inventory.json()["rows"]] == [bundle["id"]]
        options = client.get("/api/bundles/sewing-receive-options", params={"q": key}, headers=auth_headers)
        assert [row["production_order_id"] for row in options.json()] == [bundle["production_order_id"]]
    label = client.get(f"/api/bundles/{bundle['id']}/label", headers=auth_headers)
    assert label.status_code == 200 and current in label.text and old not in label.text
    assert client.get("/api/bundles/lookup", params={"code": old}).status_code == 401


def test_old_bundle_alias_handoff_preserves_factory_scope_and_duplicate_guard(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    old = _legacy_alias(bundle)
    foreign = _factory_headers("BST")
    options = client.get("/api/bundles/sewing-receive-options", params={"q": old}, headers=foreign)
    assert options.status_code == 200 and options.json() == []
    denied = client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=foreign)
    assert denied.status_code == 403, denied.text
    accepted = client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=auth_headers)
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        sewing = db.query(WorkOrder).filter_by(production_order_id=bundle["production_order_id"], operation="sewing").one()
        sewing.actual_output_qty = sewing.passed_qty = bundle["quantity"]
        db.add(SewingRecord(work_order_id=sewing.id, input_qty=bundle["quantity"], sewn_qty=bundle["quantity"],
                            passed_qty=bundle["quantity"], failed_qty=0, rework_qty=0, rejected_qty=0))
        db.commit()
    old_qr = f"BUNDLE:{old}|{bundle['barcode']}"
    denied = client.post("/api/packaging/receive-from-sewing", json={"bundle_code": old_qr}, headers=foreign)
    assert denied.status_code == 403, denied.text
    received = client.post("/api/packaging/receive-from-sewing", json={"bundle_code": old_qr}, headers=auth_headers)
    assert received.status_code == 201, received.text
    assert received.json()["bundle_no"] == bundle["bundle_no"]
    for key in (old, bundle["bundle_no"], bundle["barcode"]):
        duplicate = client.post("/api/packaging/receive-from-sewing", json={"bundle_code": key}, headers=auth_headers)
        assert duplicate.status_code == 409, duplicate.text
    with SessionLocal() as db:
        assert db.query(PackagingReceipt).filter_by(bundle_id=bundle["id"]).count() == 1


def test_conflicting_bundle_qr_rejected_in_all_lookup_and_handoff_paths(client, auth_headers):
    first = _create_bundle_for_scan(client, auth_headers)
    second = _create_bundle_for_scan(client, auth_headers)
    old = _legacy_alias(first)
    mixed = f"BUNDLE:{old}|{second['barcode']}"
    for route in ("/api/bundles/lookup?code=", "/api/bundles/barcode/", "/api/barcode/bundle/", "/api/traceability/bundle/"):
        response = client.get(route + quote(mixed, safe=""), headers=auth_headers)
        assert response.status_code == 409, response.text
    response = client.post("/api/packaging/receive-from-sewing", json={"bundle_code": mixed}, headers=auth_headers)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.query(PackagingReceipt).filter(PackagingReceipt.bundle_id.in_([first["id"], second["id"]])).count() == 0

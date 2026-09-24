from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, LegacyStockReceipt, Model, Package, PackageChangeRequest, PackageItem
from app.schemas.tracking import PackageEditPayload
from app.services.packages import (
    _normalize_package_items,
    _validate_batch_allocations,
    normalize_package_edit_payload,
)


def _size_lines(count: int) -> list[dict]:
    return [{"size": "M", "quantity": 1} for _ in range(count)]


def _allocations(count: int) -> list[dict]:
    return [{"production_batch_id": 1, "quantity": 1} for _ in range(count)]


@pytest.mark.parametrize("field,rows", [
    ("items", _size_lines),
    ("batch_allocations", _allocations),
])
def test_package_edit_arrays_accept_200_rows_and_reject_201(field, rows):
    assert len(getattr(PackageEditPayload.model_validate({field: rows(200)}), field)) == 200
    with pytest.raises(ValidationError):
        PackageEditPayload.model_validate({field: rows(201)})


def test_package_edit_service_rejects_oversized_items_before_normalization():
    pkg = SimpleNamespace(model_id=1, color="blue", items=[])
    payload = {"items": _size_lines(201)}
    with pytest.raises(HTTPException, match="more than 200 size lines"):
        _normalize_package_items(pkg, payload, "blue")
    assert len(payload["items"]) == 201


def test_unsubmitted_legacy_item_rows_remain_available_for_unrelated_edits():
    items = [SimpleNamespace(id=index, model_id=1, color="blue", size="M", quantity=1) for index in range(201)]
    pkg = SimpleNamespace(model_id=1, color="blue", items=items)
    assert len(_normalize_package_items(pkg, {"notes": "updated"}, "blue")) == 201


def test_package_edit_service_rejects_oversized_allocations_before_database_reads():
    with pytest.raises(HTTPException, match="more than 200 batch allocations"):
        _validate_batch_allocations(None, None, _allocations(201), 201)


def test_oversized_package_change_request_has_no_request_or_audit_write(client, auth_headers):
    with SessionLocal() as db:
        before = (db.query(PackageChangeRequest).count(), db.query(AuditLog).count())

    payload = {"request_type": "edit", "payload": {"items": _size_lines(201)}}
    rejected = client.post("/api/packages/1/change-requests", headers=auth_headers, json=payload)
    unauthenticated = client.post("/api/packages/1/change-requests", json=payload)

    assert rejected.status_code == 422, rejected.text
    assert unauthenticated.status_code == 401, unauthenticated.text
    with SessionLocal() as db:
        assert (db.query(PackageChangeRequest).count(), db.query(AuditLog).count()) == before


def _editable_package() -> int:
    suffix = uuid4().hex[:12]
    with SessionLocal() as db:
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        receipt = LegacyStockReceipt(
            source_system="DB03", source_warehouse_id="test", source_record_id=suffix,
            source_checksum="0" * 64, source_payload={},
        )
        db.add(receipt)
        db.flush()
        pkg = Package(
            package_no=f"DB03-EDIT-{suffix}", barcode=f"DB03-EDIT-QR-{suffix}",
            packaging_department_code="PKG", legacy_receipt_id=receipt.id, model_id=model_id, color="blue",
            package_type="bag", total_quantity=1, capacity=10, status="packed",
        )
        db.add(pkg)
        db.flush()
        db.add(PackageItem(package_id=pkg.id, model_id=model_id, color="blue", size="M", quantity=1))
        db.commit()
        return int(pkg.id)


@pytest.mark.parametrize("edit", [
    {"color": "x" * 65},
    {"notes": "x" * 4097},
    {"notes": "🍃" * 1025},
])
def test_changed_package_edit_text_rejects_without_request_or_audit_write(client, auth_headers, edit):
    package_id = _editable_package()
    with SessionLocal() as db:
        before = (db.query(PackageChangeRequest).count(), db.query(AuditLog).count())

    rejected = client.post(
        f"/api/packages/{package_id}/change-requests", headers=auth_headers,
        json={"request_type": "edit", "payload": edit},
    )

    assert rejected.status_code == 400, rejected.text
    with SessionLocal() as db:
        assert (db.query(PackageChangeRequest).count(), db.query(AuditLog).count()) == before
        assert db.get(Package, package_id).notes is None


def test_package_edit_text_accepts_boundary_and_unchanged_legacy_values():
    pkg = SimpleNamespace(
        model_id=1, color="blue", items=[SimpleNamespace(id=1, model_id=1, color="blue", size="M", quantity=1)],
        package_type="bag", capacity=10, weight_kg=None, warehouse_id=None, storage_cell=None,
        storage_shelf=None, production_order_id=None, notes="legacy" * 1000,
    )
    normalized = normalize_package_edit_payload(None, pkg, {"color": "C" * 64})
    assert normalized["color"] == "C" * 64
    assert normalized["notes"] == pkg.notes
    assert normalize_package_edit_payload(None, pkg, {"notes": "N" * 4096})["notes"] == "N" * 4096

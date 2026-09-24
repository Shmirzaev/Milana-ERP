from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, PackageChangeRequest
from app.schemas.tracking import PackageEditPayload
from app.services.packages import _normalize_package_items, _validate_batch_allocations


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

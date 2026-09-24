from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Model


_MAX_PAID_OPERATION_ROWS = 1000


def _paid_operation_rows(count: int) -> list[dict[str, str | int]]:
    return [{"id": f"op-{index}", "name": f"Operation {index}"} for index in range(count)]


@pytest.mark.parametrize(
    "details",
    [
        {"general": []},
        {"costing": "12"},
        {"paid_operations": "not-a-list"},
    ],
)
def test_model_create_rejects_malformed_established_detail_objects_without_insert(
    client, auth_headers, details
):
    code = f"DB03-{uuid4().hex[:10]}"

    response = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Invalid details", "details_json": details},
    )

    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(Model.id).filter(Model.code == code).first() is None


def test_model_update_rejects_malformed_detail_objects_without_changing_existing_row(
    client, auth_headers
):
    suffix = uuid4().hex[:10]
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={
            "code": f"DB03-{suffix}",
            "name": "Valid details",
            "details_json": {
                "general": {"model_no": f"DB03-{suffix}"},
                "costing": {"notes": "legacy free-form costing metadata"},
                "legacy_extension": {"format": 1, "opaque": ["keep", 7]},
            },
        },
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json={"name": "Should not persist", "details_json": {"general": None}},
    )

    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        model = db.get(Model, model_id)
        assert model.name == "Valid details"
        assert model.details_json == {
            "general": {"model_no": f"DB03-{suffix}"},
            "costing": {"notes": "legacy free-form costing metadata"},
            "legacy_extension": {"format": 1, "opaque": ["keep", 7]},
        }


def test_model_unrelated_edit_preserves_legacy_detail_shapes(client, auth_headers):
    suffix = uuid4().hex[:10]
    code = f"LEGACY{suffix}"
    legacy_details = {
        "general": {"modelNo": code, "custom": ["x", 3]},
        "costing": {"notes": "older free-form value"},
        "unknown_v2_extension": {"vendor": "legacy", "values": [1, None, "x"]},
    }
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={
            "code": code,
            "name": "Legacy metadata",
            "details_json": {"general": {"model_no": code}},
        },
    )
    assert created.status_code == 201, created.text
    with SessionLocal() as db:
        model = db.get(Model, created.json()["id"])
        model.details_json = legacy_details
        db.commit()

    updated = client.patch(
        f"/api/models/{created.json()['id']}",
        headers=auth_headers,
        json={
            "code": created.json()["code"],
            "name": created.json()["name"],
            "description": "edited independently",
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["details_json"] == legacy_details


def test_model_create_accepts_paid_operation_row_boundary(client, auth_headers):
    suffix = uuid4().hex[:10]
    rows = _paid_operation_rows(_MAX_PAID_OPERATION_ROWS)

    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={
            "code": f"PAID-OPS-BOUND-{suffix}",
            "name": "Paid operation boundary",
            "details_json": {"paid_operations": rows},
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["details_json"]["paid_operations"] == rows


def test_model_create_rejects_paid_operation_rows_over_limit_without_insert(client, auth_headers):
    suffix = uuid4().hex[:10]
    code = f"PAID-OPS-OVER-{suffix}"

    response = client.post(
        "/api/models",
        headers=auth_headers,
        json={
            "code": code,
            "name": "Too many paid operations",
            "details_json": {"paid_operations": _paid_operation_rows(_MAX_PAID_OPERATION_ROWS + 1)},
        },
    )

    assert response.status_code == 422, response.text
    assert f"details_json.paid_operations cannot exceed {_MAX_PAID_OPERATION_ROWS} rows" in response.text
    with SessionLocal() as db:
        assert db.query(Model.id).filter(Model.code == code).first() is None


def test_paid_operation_row_cap_preserves_auth_and_missing_model_precedence(client, auth_headers):
    body = {
        "code": "UNUSED-OVER-LIMIT",
        "name": "Too many paid operations",
        "details_json": {"paid_operations": _paid_operation_rows(_MAX_PAID_OPERATION_ROWS + 1)},
    }
    with SessionLocal() as db:
        before = (
            db.query(Model.id).count(),
            db.query(AuditLog.id).filter_by(entity_type="Model").count(),
        )

    unauthenticated = client.post("/api/models", json=body)
    missing_model = client.patch(
        "/api/models/2147483647",
        headers=auth_headers,
        json={
            "code": "MISSING-OVER-LIMIT",
            "name": "Missing model",
            "details_json": body["details_json"],
        },
    )

    assert unauthenticated.status_code == 401, unauthenticated.text
    assert missing_model.status_code == 404, missing_model.text
    with SessionLocal() as db:
        assert (
            db.query(Model.id).count(),
            db.query(AuditLog.id).filter_by(entity_type="Model").count(),
        ) == before


def test_model_patch_rejects_changed_oversized_paid_operations_without_write(client, auth_headers):
    suffix = uuid4().hex[:10]
    code = f"PAID-OPS-PATCH-{suffix}"
    original = {
        "general": {"model_no": code},
        "paid_operations": _paid_operation_rows(_MAX_PAID_OPERATION_ROWS),
    }
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Paid operation update", "details_json": original},
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json={
            "code": code,
            "name": "Should not persist",
            "details_json": {"paid_operations": _paid_operation_rows(_MAX_PAID_OPERATION_ROWS + 1)},
        },
    )

    assert response.status_code == 422, response.text
    assert f"details_json.paid_operations cannot exceed {_MAX_PAID_OPERATION_ROWS} rows" in response.text
    with SessionLocal() as db:
        model = db.get(Model, model_id)
        assert model.name == "Paid operation update"
        assert model.details_json == original
        assert db.query(AuditLog.id).filter_by(entity_type="Model", entity_id=model_id).count() == 1


def test_model_patch_preserves_exact_unchanged_oversized_legacy_paid_operations(client, auth_headers):
    suffix = uuid4().hex[:10]
    code = f"PAID-OPS-LEGACY-{suffix}"
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Legacy paid operation list"},
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    legacy_details = {
        "general": {"model_no": code},
        "paid_operations": _paid_operation_rows(_MAX_PAID_OPERATION_ROWS + 1),
    }
    with SessionLocal() as db:
        model = db.get(Model, model_id)
        model.details_json = legacy_details
        db.commit()

    updated = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json={"code": code, "name": "Legacy list retained", "details_json": legacy_details},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["details_json"] == legacy_details
    with SessionLocal() as db:
        assert db.get(Model, model_id).details_json == legacy_details


def test_model_paid_operations_endpoint_rejects_oversized_list_without_write(client, auth_headers):
    suffix = uuid4().hex[:10]
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": f"PAID-OPS-ENDPOINT-{suffix}", "name": "Paid operation endpoint"},
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    with SessionLocal() as db:
        original = db.get(Model, model_id).details_json
        before_audits = db.query(AuditLog.id).filter_by(entity_type="Model", entity_id=model_id).count()

    response = client.patch(
        f"/api/models/{model_id}/paid-operations",
        headers=auth_headers,
        json={"paid_operations": _paid_operation_rows(_MAX_PAID_OPERATION_ROWS + 1)},
    )

    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.get(Model, model_id).details_json == original
        assert db.query(AuditLog.id).filter_by(entity_type="Model", entity_id=model_id).count() == before_audits

from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import Model


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
    legacy_details = {
        "general": {"modelNo": "LEGACY", "custom": ["x", 3]},
        "costing": {"notes": "older free-form value"},
        "unknown_v2_extension": {"vendor": "legacy", "values": [1, None, "x"]},
    }
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={
            "code": f"LEGACY-{suffix}",
            "name": "Legacy metadata",
            "details_json": {"general": {"model_no": f"LEGACY-{suffix}"}},
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

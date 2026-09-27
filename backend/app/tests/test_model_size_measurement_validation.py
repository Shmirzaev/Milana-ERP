from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Model, ModelSize, Role, User


def _model() -> int:
    marker = uuid4().hex
    with SessionLocal.begin() as db:
        model = Model(
            code=f"MEASURE-{marker}",
            name="Measurement validation model",
            catalog_scope="standard",
            status="draft",
        )
        db.add(model)
        db.flush()
        return model.id


def _size_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(ModelSize).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "ModelSize").count(),
        )


def _unprivileged_headers() -> dict[str, str]:
    marker = uuid4().hex
    with SessionLocal.begin() as db:
        role = Role(name=f"No model measurement access {marker}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="No model measurement access",
            email=f"no-model-measurement-{marker}@example.invalid",
            password_hash="unused",
            role_id=role.id,
            factory_code="MIL",
        )
        db.add(user)
        db.flush()
        user_id = user.id
    return {"Authorization": f"Bearer {create_access_token(user_id, {'factory_code': 'MIL'})}"}


def test_model_size_accepts_complete_established_measurement_shape(client, auth_headers):
    model_id = _model()
    measurements = {
        "chest": 92,
        "waist": 71.5,
        "hip": 98,
        "length": 120.25,
        "sleeve": 61,
    }

    response = client.post(
        f"/api/models/{model_id}/sizes",
        headers=auth_headers,
        json={"size": "M", "measurement_json": measurements},
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        saved = db.get(ModelSize, response.json()["id"])
        assert saved.measurement_json == measurements


@pytest.mark.parametrize(
    "measurements",
    [
        {"shoulder": 40},
        {"chest": {"value": 92}},
        {"waist": "71.5"},
        {"hip": [98]},
        {"length": True},
    ],
)
def test_model_size_rejects_malformed_measurements_without_side_effects(
    client, auth_headers, measurements,
):
    model_id = _model()
    before = _size_counts()

    response = client.post(
        f"/api/models/{model_id}/sizes",
        headers=auth_headers,
        json={"size": "M", "measurement_json": measurements},
    )

    assert response.status_code == 422, response.text
    assert _size_counts() == before


def test_model_size_validation_preserves_auth_and_not_found_precedence(client, auth_headers):
    invalid = {"chest": {"value": 92}}
    model_id = _model()
    before = _size_counts()

    denied = client.post(
        f"/api/models/{model_id}/sizes",
        headers=_unprivileged_headers(),
        json={"size": "M", "measurement_json": invalid},
    )
    assert denied.status_code == 403, denied.text

    missing = client.post(
        "/api/models/2147483647/sizes",
        headers=auth_headers,
        json={"size": "M", "measurement_json": invalid},
    )
    assert missing.status_code == 404, missing.text
    assert _size_counts() == before


def test_legacy_model_size_measurements_remain_readable(client, auth_headers):
    model_id = _model()
    legacy = {"legacy_extension": {"value": [1, 2, 3]}}
    with SessionLocal.begin() as db:
        size = ModelSize(model_id=model_id, size="Legacy", measurement_json=legacy)
        db.add(size)

    response = client.get(f"/api/models/{model_id}", headers=auth_headers)

    assert response.status_code == 200, response.text
    saved = next(row for row in response.json()["sizes"] if row["size"] == "Legacy")
    assert saved["measurement_json"] == legacy

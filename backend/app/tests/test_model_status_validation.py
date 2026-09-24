from uuid import uuid4

import pytest

from app.models import AuditLog, Model
from app.tests.conftest import TestSessionLocal


VALID_STATUSES = ("draft", "sample", "approved", "archived")


def _create_model(client, auth_headers, *, status: str = "draft") -> int:
    code = f"DB02STATUS{uuid4().hex[:10].upper()}"
    response = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Status validation model", "status": status},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _legacy_model() -> int:
    marker = uuid4().hex[:12].upper()
    with TestSessionLocal() as db:
        model = Model(
            code=f"DB02LEGACY{marker}",
            name="Legacy status model",
            status="legacy_review_state",
        )
        db.add(model)
        db.commit()
        return int(model.id)


def _update_fields(model_id: int, *, name: str | None = None) -> dict[str, str]:
    with TestSessionLocal() as db:
        model = db.get(Model, model_id)
        return {"code": model.code, "name": name or model.name}


@pytest.mark.parametrize("status", VALID_STATUSES)
def test_model_create_accepts_established_status_vocabulary(client, auth_headers, status):
    model_id = _create_model(client, auth_headers, status=status)
    with TestSessionLocal() as db:
        assert db.get(Model, model_id).status == status


@pytest.mark.parametrize("status", VALID_STATUSES)
def test_model_patch_accepts_established_status_vocabulary(client, auth_headers, status):
    model_id = _create_model(client, auth_headers)
    payload = _update_fields(model_id)
    payload["status"] = status
    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == status


def test_model_create_rejects_unknown_status_without_write_or_audit(client, auth_headers):
    code = f"DB02INVALID{uuid4().hex[:10].upper()}"
    with TestSessionLocal() as db:
        before = (db.query(Model).count(), db.query(AuditLog).count())

    response = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Rejected status model", "status": "retired"},
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid model status"}
    with TestSessionLocal() as db:
        assert db.query(Model).filter(Model.code == code).first() is None
        assert (db.query(Model).count(), db.query(AuditLog).count()) == before


def test_model_patch_rejects_unknown_status_without_mutation_or_audit(client, auth_headers):
    model_id = _create_model(client, auth_headers)
    with TestSessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    payload = _update_fields(model_id, name="Must not be written")
    payload["status"] = "retired"
    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid model status"}
    with TestSessionLocal() as db:
        model = db.get(Model, model_id)
        assert model.name == "Status validation model"
        assert model.status == "draft"
        assert db.query(AuditLog).count() == before_audits


def test_model_patch_allows_unchanged_legacy_status_during_unrelated_edit(client, auth_headers):
    model_id = _legacy_model()
    payload = _update_fields(model_id, name="Renamed legacy model")
    payload["status"] = "legacy_review_state"
    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed legacy model"
    assert response.json()["status"] == "legacy_review_state"


def test_model_patch_rejects_changing_legacy_status_to_unknown_without_write(client, auth_headers):
    model_id = _legacy_model()
    with TestSessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    payload = _update_fields(model_id, name="Must not be written")
    payload["status"] = "retired"
    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 400, response.text
    with TestSessionLocal() as db:
        model = db.get(Model, model_id)
        assert model.name == "Legacy status model"
        assert model.status == "legacy_review_state"
        assert db.query(AuditLog).count() == before_audits


def test_model_status_validation_preserves_resource_and_auth_precedence(client, auth_headers):
    missing = client.patch(
        "/api/models/2147483647",
        headers=auth_headers,
        json={"code": "MISSING", "name": "Missing", "status": "retired"},
    )
    assert missing.status_code == 404, missing.text

    unauthorized = client.post(
        "/api/models",
        json={"code": "UNAUTHORIZED", "name": "Model", "status": "retired"},
    )
    assert unauthorized.status_code == 401, unauthorized.text


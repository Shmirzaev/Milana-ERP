"""Keep editable model payroll JSON in its established list-of-objects shape."""

from copy import deepcopy
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Model


def _model() -> tuple[int, dict]:
    suffix = uuid4().hex[:8].upper()
    details = {
        "general": {"model_no": f"DB03-{suffix}"},
        "costing": {"target_margin_pct": 20},
        "paid_operations": [{
            "id": f"sew-{suffix}",
            "selected": True,
            "section": "sewing",
            "code": f"SEW-{suffix}",
            "name": "Sewing",
            "rate": "100",
            "legacy_extension": {"source": "existing-client"},
        }],
    }
    with SessionLocal() as db:
        model = Model(
            code=f"DB03-{suffix}",
            name=f"DB03 model {suffix}",
            status="draft",
            details_json=deepcopy(details),
        )
        db.add(model)
        db.commit()
        return int(model.id), details


def _update_payload(model_id: int, details: dict) -> dict:
    with SessionLocal() as db:
        model = db.get(Model, model_id)
        return {
            "code": model.code,
            "name": model.name,
            "status": model.status,
            "details_json": details,
        }


def _snapshot(model_id: int) -> tuple[dict, int]:
    with SessionLocal() as db:
        return deepcopy(db.get(Model, model_id).details_json), db.query(AuditLog).count()


@pytest.mark.parametrize(("paid_operations", "detail"), [
    ({"id": "not-a-list"}, "details_json.paid_operations must be a list"),
    ([{"id": "valid"}, "not-an-object"], "details_json.paid_operations[1] must be an object"),
])
def test_model_update_rejects_malformed_paid_operation_json_without_writes(
    client, auth_headers, paid_operations, detail,
):
    model_id, original = _model()
    before = _snapshot(model_id)
    malformed = {**deepcopy(original), "paid_operations": paid_operations}

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, malformed),
    )

    assert response.status_code == 422, response.text
    assert response.json() == {"detail": detail}
    assert _snapshot(model_id) == before


@pytest.mark.parametrize("key", ["paid_operations", "paidOperations"])
def test_model_update_preserves_supported_operation_aliases_and_extensible_rows(client, auth_headers, key):
    model_id, original = _model()
    operation = deepcopy(original["paid_operations"][0])
    details = {
        "general": deepcopy(original["general"]),
        "costing": deepcopy(original["costing"]),
        "future_section": {"kept": True},
        key: [operation],
    }

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, details),
    )

    assert response.status_code == 200, response.text
    assert response.json()["details_json"] == details
    with SessionLocal() as db:
        assert db.get(Model, model_id).details_json == details


def test_model_details_structure_validation_preserves_authentication(client):
    model_id, original = _model()
    before = _snapshot(model_id)
    malformed = {**deepcopy(original), "paid_operations": "not-a-list"}

    response = client.patch(f"/api/models/{model_id}", json=_update_payload(model_id, malformed))

    assert response.status_code == 401
    assert _snapshot(model_id) == before


def test_model_details_structure_validation_preserves_missing_model_precedence(client, auth_headers):
    response = client.patch(
        "/api/models/2147483647",
        headers=auth_headers,
        json={
            "code": "MISSING",
            "name": "Missing",
            "status": "draft",
            "details_json": {"paid_operations": "not-a-list"},
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Model not found"}

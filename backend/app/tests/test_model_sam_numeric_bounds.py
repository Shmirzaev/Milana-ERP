from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Model


MAX_SAM_MINUTES = Decimal("999999.99")


def _payload(marker: str, **overrides) -> dict:
    return {
        "code": f"SAM-{marker}",
        "name": f"SAM bound model {marker}",
        "status": "draft",
        "sam_minutes": "12.50",
        **overrides,
    }


def _model_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(Model).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "Model").count(),
        )


def test_model_sam_accepts_exact_signed_numeric_boundaries(client, auth_headers):
    marker = uuid4().hex[:12]
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json=_payload(marker, sam_minutes=str(MAX_SAM_MINUTES)),
    )
    assert created.status_code == 201, created.text
    assert Decimal(str(created.json()["sam_minutes"])) == MAX_SAM_MINUTES

    updated = client.patch(
        f"/api/models/{created.json()['id']}",
        headers=auth_headers,
        json={
            "code": created.json()["code"],
            "name": created.json()["name"],
            "sam_minutes": str(-MAX_SAM_MINUTES),
        },
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(str(updated.json()["sam_minutes"])) == -MAX_SAM_MINUTES


@pytest.mark.parametrize("sam_minutes", ["NaN", "Infinity", "-Infinity", "1000000", "-1000000"])
def test_model_create_rejects_unstorable_sam_without_writes(
    client, auth_headers, sam_minutes,
):
    before = _model_counts()

    response = client.post(
        "/api/models",
        headers=auth_headers,
        json=_payload(uuid4().hex[:12], sam_minutes=sam_minutes),
    )

    assert response.status_code == 422, response.text
    assert _model_counts() == before


def test_model_patch_rejects_unstorable_sam_without_mutation(client, auth_headers):
    marker = uuid4().hex[:12]
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json=_payload(marker),
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    before = _model_counts()

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json={
            "code": created.json()["code"],
            "name": "Changed by invalid request",
            "sam_minutes": "1000000",
        },
    )

    assert response.status_code == 422, response.text
    assert _model_counts() == before
    with SessionLocal() as db:
        model = db.get(Model, model_id)
        assert model.name == created.json()["name"]
        assert model.sam_minutes == Decimal("12.50")


def test_model_sam_validation_preserves_auth_resource_and_duplicate_precedence(
    client, auth_headers,
):
    marker = uuid4().hex[:12]
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json=_payload(marker),
    )
    assert created.status_code == 201, created.text

    denied = client.post(
        "/api/models",
        json=_payload(f"DENIED-{marker}", sam_minutes="Infinity"),
    )
    assert denied.status_code == 401, denied.text

    missing = client.patch(
        "/api/models/2147483647",
        headers=auth_headers,
        json=_payload(f"MISSING-{marker}", sam_minutes="Infinity"),
    )
    assert missing.status_code == 404, missing.text

    duplicate = client.post(
        "/api/models",
        headers=auth_headers,
        json={
            **_payload(f"DUPLICATE-{marker}", sam_minutes="Infinity"),
            "code": created.json()["code"],
        },
    )
    assert duplicate.status_code == 400, duplicate.text

from copy import deepcopy
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Model


def _make_model(costing: dict) -> int:
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        model = Model(
            code=f"COST-{marker}",
            name=f"Cost JSON {marker}",
            status="draft",
            details_json={
                "general": {"model_no": f"COST-{marker}"},
                "costing": deepcopy(costing),
                "future_section": {"kept": True},
            },
        )
        db.add(model)
        db.commit()
        return int(model.id)


def _snapshot(model_id: int) -> tuple[dict, int]:
    with SessionLocal() as db:
        model = db.get(Model, model_id)
        audits = db.query(AuditLog).filter(
            AuditLog.entity_type == "Model",
            AuditLog.entity_id == model_id,
        ).count()
        return deepcopy(model.details_json), audits


def _model_count() -> int:
    with SessionLocal() as db:
        return db.query(Model).count()


def _update_payload(model_id: int, details: dict, *, name: str | None = None) -> dict:
    with SessionLocal() as db:
        model = db.get(Model, model_id)
        return {
            "code": model.code,
            "name": name or model.name,
            "status": model.status,
            "details_json": details,
        }


@pytest.mark.parametrize(
    "value",
    ["not-a-number", True, {"value": 12}, float("inf"), 10**400, None],
)
def test_model_update_rejects_malformed_costing_values_without_writes(
    client,
    auth_headers,
    value,
):
    model_id = _make_model({"labor_pct": 12})
    before = _snapshot(model_id)
    details = deepcopy(before[0])
    details["costing"]["labor_pct"] = value

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, details),
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "details_json.costing.labor_pct must be a finite number",
    }
    assert _snapshot(model_id) == before


def test_model_update_accepts_established_costing_numbers_and_extensions(client, auth_headers):
    model_id = _make_model({"labor_pct": 12, "target_margin_pct": 20})
    details, _ = _snapshot(model_id)
    details["costing"]["labor_pct"] = 14.5

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, details),
    )

    assert response.status_code == 200, response.text
    assert response.json()["details_json"]["costing"]["labor_pct"] == 14.5
    assert response.json()["details_json"]["future_section"] == {"kept": True}


def test_model_update_allows_unchanged_legacy_costing_value(client, auth_headers):
    model_id = _make_model({"labor_pct": "legacy-invalid"})
    details, _ = _snapshot(model_id)
    payload = _update_payload(model_id, details, name="Unrelated model edit")

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Unrelated model edit"
    assert response.json()["details_json"]["costing"]["labor_pct"] == "legacy-invalid"
    assert _snapshot(model_id)[0]["costing"]["labor_pct"] == "legacy-invalid"


def test_model_update_rejects_new_null_costing_value_without_writes(client, auth_headers):
    model_id = _make_model({})
    before = _snapshot(model_id)
    details = deepcopy(before[0])
    details["costing"]["labor_pct"] = None

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, details),
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "details_json.costing.labor_pct must be a finite number",
    }
    assert _snapshot(model_id) == before


@pytest.mark.parametrize("value", ["not-a-number", None])
def test_model_create_rejects_non_numeric_costing_values_without_writes(
    client,
    auth_headers,
    value,
):
    marker = uuid4().hex[:10].upper()
    before = _model_count()

    response = client.post(
        "/api/models",
        headers=auth_headers,
        json={
            "code": f"COST-{marker}",
            "name": f"Cost JSON {marker}",
            "status": "draft",
            "details_json": {"costing": {"target_margin_pct": value}},
        },
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "details_json.costing.target_margin_pct must be a finite number",
    }
    assert _model_count() == before


from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.models import AuditLog, Model
from app.tests.conftest import TestSessionLocal


_MAX_SOURCE_JSON_BYTES = 16 * 1024
_MAX_SOURCE_JSON_DEPTH = 16


@pytest.fixture
def scoped_model_id():
    with TestSessionLocal() as db:
        model = Model(
            code=f"FC-SOURCE-{uuid4().hex[:8]}",
            name="Forecast source test model",
            factory_code="MIL",
            status="approved",
        )
        db.add(model)
        db.commit()
        return int(model.id)


def _recommendation(source_json, model_id):
    return {
        "recommendation_type": "item_reorder",
        "suggested_quantity": 1,
        "source_json": source_json,
        "model_id": model_id,
    }


def _recommendations(client, headers):
    response = client.get("/api/forecasting/recommendations", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _forecast_create_audit_count():
    with TestSessionLocal() as db:
        return db.query(AuditLog.id).filter(
            AuditLog.action == "create_forecast_recommendation"
        ).count()


def _nested_source(depth):
    value = True
    for index in range(depth - 1):
        value = {"child": value}
    return {"root": value}


def test_forecast_source_json_accepts_exact_byte_limit_and_rejects_over_limit_without_write(
    client, auth_headers, scoped_model_id
):
    before = _recommendations(client, auth_headers)
    audit_count = _forecast_create_audit_count()
    exact_source = {"padding": "x" * (_MAX_SOURCE_JSON_BYTES - len('{"padding":""}'))}
    assert len(json.dumps(exact_source, separators=(",", ":")).encode()) == (
        _MAX_SOURCE_JSON_BYTES
    )

    accepted = client.post(
        "/api/forecasting/recommendations",
        json=_recommendation(exact_source, scoped_model_id),
        headers=auth_headers,
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["source_json"] == exact_source

    too_large = {"padding": exact_source["padding"] + "x"}
    rejected = client.post(
        "/api/forecasting/recommendations",
        json=_recommendation(too_large, scoped_model_id),
        headers=auth_headers,
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"] == "source_json exceeds the 16 KiB limit"

    after = _recommendations(client, auth_headers)
    assert len(after) == len(before) + 1
    assert after[0]["id"] == accepted.json()["id"]
    assert _forecast_create_audit_count() == audit_count + 1


def test_forecast_source_json_rejects_excessive_depth_without_write(client, auth_headers, scoped_model_id):
    before = _recommendations(client, auth_headers)
    audit_count = _forecast_create_audit_count()
    accepted = client.post(
        "/api/forecasting/recommendations",
        json=_recommendation(_nested_source(_MAX_SOURCE_JSON_DEPTH), scoped_model_id),
        headers=auth_headers,
    )
    assert accepted.status_code == 201, accepted.text

    rejected = client.post(
        "/api/forecasting/recommendations",
        json=_recommendation(_nested_source(_MAX_SOURCE_JSON_DEPTH + 1), scoped_model_id),
        headers=auth_headers,
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"] == "source_json exceeds the maximum nesting depth"

    after = _recommendations(client, auth_headers)
    assert len(after) == len(before) + 1
    assert after[0]["id"] == accepted.json()["id"]
    assert _forecast_create_audit_count() == audit_count + 1


def test_forecast_source_json_validation_follows_auth_and_reference_checks(client, auth_headers, scoped_model_id):
    recommendation_count = len(_recommendations(client, auth_headers))
    audit_count = _forecast_create_audit_count()
    sales_token = client.post(
        "/api/auth/token",
        data={"username": "sales@example.com", "password": "demo12345"},
    )
    assert sales_token.status_code == 200, sales_token.text
    forbidden = client.post(
        "/api/forecasting/recommendations",
        json=_recommendation({"padding": "x" * _MAX_SOURCE_JSON_BYTES}, scoped_model_id),
        headers={"Authorization": f"Bearer {sales_token.json()['access_token']}"},
    )
    assert forbidden.status_code == 403, forbidden.text

    dangling = client.post(
        "/api/forecasting/recommendations",
        json={
            **_recommendation({"padding": "x" * _MAX_SOURCE_JSON_BYTES}, scoped_model_id),
            "item_id": 2_147_483_647,
        },
        headers=auth_headers,
    )
    assert dangling.status_code == 400, dangling.text
    assert dangling.json()["detail"] == "item_id references a missing record"
    assert len(_recommendations(client, auth_headers)) == recommendation_count
    assert _forecast_create_audit_count() == audit_count


def test_forecast_source_json_rejects_non_finite_values_without_write(client, auth_headers, scoped_model_id):
    before = _recommendations(client, auth_headers)
    audit_count = _forecast_create_audit_count()
    rejected = client.post(
        "/api/forecasting/recommendations",
        json=_recommendation({"ratio": float("nan")}, scoped_model_id),
        headers=auth_headers,
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"] == "source_json must contain finite numbers"
    assert _recommendations(client, auth_headers) == before
    assert _forecast_create_audit_count() == audit_count

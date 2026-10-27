"""The forecast review operation: canonical status vocabulary and owned write.

The patch contract keeps the four accepted status strings it always accepted.
The stored value, the audit action name and the legacy response contract are
unchanged; only the typed vocabulary and the location of the mapped write moved.
"""
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.libs.dto.planning.forecast_recommendation_input import (
    STORAGE_MIN_POSITIVE_QUANTITY,
    ForecastRecommendationIn,
)
from app.libs.dto.planning.forecast_recommendation_update import ForecastRecommendationPatch
from app.libs.enums.planning import ForecastRecommendationStatus
from app.main import app
from app.models.planning import forecasting_recommendations_service as service
from app.schemas import AuditLog, ForecastRecommendation, Model, Role, User


ACCEPTED_STATUSES = ["open", "accepted", "dismissed", "converted"]


def _review_headers() -> tuple[dict[str, str], int]:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        role = Role(name=f"Forecast review {marker}", permissions=["forecasting.view", "forecasting.manage"])
        db.add(role)
        db.flush()
        user = User(
            name=f"Forecast review {marker}",
            email=f"forecast-review-{marker}@example.invalid",
            password_hash="unused-forecast-review-hash",
            role_id=role.id,
            factory_code="MIL",
            is_active=True,
        )
        db.add(user)
        db.commit()
        user_id = int(user.id)
        token = create_access_token(user_id, {"factory_code": "MIL"})
    return {"Authorization": f"Bearer {token}"}, user_id


def _recommendation(status: str = "open") -> int:
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        model = Model(
            code=f"FC-REVIEW-{marker}",
            name=f"Forecast review model {marker}",
            factory_code="MIL",
            status="approved",
        )
        db.add(model)
        db.flush()
        row = ForecastRecommendation(
            recommendation_type="item_reorder",
            status=status,
            model_id=model.id,
            suggested_quantity=10,
            unit="pcs",
        )
        db.add(row)
        db.commit()
        return int(row.id)


def test_review_patch_keeps_the_same_four_accepted_statuses():
    for value in ACCEPTED_STATUSES:
        assert ForecastRecommendationPatch(status=value).status == value
    for value in ["OPEN", " accepted", "converted ", "unknown", "", None, 1]:
        with pytest.raises(ValidationError):
            ForecastRecommendationPatch(status=value)


def test_review_patch_uses_the_canonical_enum_member():
    payload = ForecastRecommendationPatch(status="accepted")
    assert payload.status is ForecastRecommendationStatus.ACCEPTED
    assert isinstance(payload.status, ForecastRecommendationStatus)


def test_review_writes_the_plain_stored_status_and_the_reviewer(client):
    headers, user_id = _review_headers()
    row_id = _recommendation()

    response = client.patch(
        f"/api/forecasting/recommendations/{row_id}",
        json={"status": "dismissed"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "dismissed"
    with SessionLocal() as db:
        stored = db.get(ForecastRecommendation, row_id)
        assert stored.status == "dismissed"
        assert type(stored.status) is str
        assert stored.reviewed_by == user_id
        assert stored.reviewed_at is not None


def test_review_audit_action_keeps_the_plain_status_name(client):
    headers, user_id = _review_headers()
    row_id = _recommendation()

    response = client.patch(
        f"/api/forecasting/recommendations/{row_id}",
        json={"status": "accepted"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "ForecastRecommendation", AuditLog.entity_id == row_id)
            .one()
        )
        assert audit.action == "accepted_forecast_recommendation"
        assert "ForecastRecommendationStatus" not in audit.action
        assert audit.old_value_json == {"status": "open"}
        assert audit.new_value_json == {"status": "accepted"}


def test_the_schema_owned_review_write_uses_the_supplied_session_and_never_commits(monkeypatch):
    headers, user_id = _review_headers()
    row_id = _recommendation()
    observed = []
    original = service.apply_forecast_recommendation_review

    def observe(db, command, row):
        commits = []

        def unexpected_commit(*args):
            commits.append(True)

        event.listen(db, "before_commit", unexpected_commit)
        try:
            assert command.status is ForecastRecommendationStatus.ACCEPTED
            assert command.reviewed_by == user_id
            assert command.reviewed_at is not None
            result = original(db, command, row)
            assert not commits, "the schema-owned write must not commit"
            observed.append(db)
            return result
        finally:
            event.remove(db, "before_commit", unexpected_commit)

    monkeypatch.setattr(service, "apply_forecast_recommendation_review", observe)
    with SessionLocal() as db:
        service.update_recommendation(
            db, row_id, ForecastRecommendationPatch(status="accepted"), ["MIL"], db.get(User, user_id)
        )
        assert observed == [db]


def test_the_review_commits_exactly_once(monkeypatch):
    headers, user_id = _review_headers()
    row_id = _recommendation()
    commits = []
    original = service.apply_forecast_recommendation_review

    def observe(db, command, row):
        event.listen(db, "before_commit", lambda *args: commits.append(True))
        return original(db, command, row)

    monkeypatch.setattr(service, "apply_forecast_recommendation_review", observe)
    with SessionLocal() as db:
        service.update_recommendation(
            db, row_id, ForecastRecommendationPatch(status="converted"), ["MIL"], db.get(User, user_id)
        )
    assert len(commits) == 1, commits


def test_review_of_a_legacy_stored_status_is_allowed_and_audited(client):
    headers, user_id = _review_headers()
    row_id = _recommendation(" OLD_STATUS ")

    response = client.patch(
        f"/api/forecasting/recommendations/{row_id}",
        json={"status": "accepted"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(ForecastRecommendation, row_id).status == "accepted"
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "ForecastRecommendation", AuditLog.entity_id == row_id)
            .one()
        )
        assert audit.old_value_json == {"status": " OLD_STATUS "}
        assert audit.new_value_json == {"status": "accepted"}


def test_review_rejects_an_unknown_status_before_any_write(client):
    headers, user_id = _review_headers()
    row_id = _recommendation()
    with SessionLocal() as db:
        before = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())

    response = client.patch(
        f"/api/forecasting/recommendations/{row_id}",
        json={"status": "not-a-status"},
        headers=headers,
    )

    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        after = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
        assert db.get(ForecastRecommendation, row_id).status == "open"
    assert after == before


def test_the_review_openapi_uses_the_canonical_status_enum():
    schema = app.openapi()
    definitions = schema["components"]["schemas"]
    patch = schema["paths"]["/api/forecasting/recommendations/{recommendation_id}"]["patch"]
    body = patch["requestBody"]["content"]["application/json"]["schema"]
    assert body["$ref"].endswith("/ForecastRecommendationPatch")
    assert definitions["ForecastRecommendationPatch"]["properties"]["status"]["$ref"].endswith(
        "/ForecastRecommendationStatus"
    )
    assert definitions["ForecastRecommendationStatus"]["enum"] == ACCEPTED_STATUSES
    assert definitions["ForecastRecommendationOut"]["properties"]["status"]["type"] == "string"


def test_the_quantity_floor_matches_the_storage_resolution():
    assert STORAGE_MIN_POSITIVE_QUANTITY == Decimal("0.00005")
    for quantity in ["0.00001", "0.00004"]:
        with pytest.raises(ValidationError):
            ForecastRecommendationIn(recommendation_type="item_reorder", suggested_quantity=quantity)
    for quantity in ["0.00005", "0.0001", "12.34567", "9999999999.9999"]:
        assert ForecastRecommendationIn(
            recommendation_type="item_reorder", suggested_quantity=quantity
        ).suggested_quantity == Decimal(quantity)


def test_a_create_below_the_storage_floor_is_refused_without_any_write(client):
    headers, user_id = _review_headers()
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        model = Model(
            code=f"FC-FLOOR-{marker}",
            name=f"Forecast floor model {marker}",
            factory_code="MIL",
            status="approved",
        )
        db.add(model)
        db.commit()
        model_id = int(model.id)
        before = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())

    refused = client.post(
        "/api/forecasting/recommendations",
        json={
            "recommendation_type": "item_reorder",
            "model_id": model_id,
            "suggested_quantity": "0.00001",
        },
        headers=headers,
    )

    assert refused.status_code == 422, refused.text
    with SessionLocal() as db:
        after = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
    assert after == before

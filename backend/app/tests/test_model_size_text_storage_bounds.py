from app.db.session import SessionLocal
from app.models import AuditLog, Model, ModelSize


def _model_id() -> int:
    with SessionLocal() as db:
        model_id = db.query(Model.id).filter(Model.catalog_scope == "standard").order_by(Model.id).scalar()
        assert model_id is not None
        return int(model_id)


def _counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.query(ModelSize).count(), db.query(AuditLog).filter(AuditLog.entity_type == "ModelSize").count()


def test_model_size_varchar_boundary_is_accepted(client, auth_headers):
    response = client.post(
        f"/api/models/{_model_id()}/sizes",
        json={"size": "S" * 32},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text


def test_model_size_overflow_is_rejected_without_writes_and_preserves_auth_reference_precedence(
    client, auth_headers
):
    model_id = _model_id()
    before = _counts()

    response = client.post(
        f"/api/models/{model_id}/sizes",
        json={"size": "S" * 33},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
    assert _counts() == before

    unauthenticated = client.post(
        f"/api/models/{model_id}/sizes",
        json={"size": "S" * 33},
    )
    assert unauthenticated.status_code == 401

    missing_model = client.post(
        "/api/models/2147483647/sizes",
        json={"size": "S" * 33},
        headers=auth_headers,
    )
    assert missing_model.status_code == 404
    assert _counts() == before

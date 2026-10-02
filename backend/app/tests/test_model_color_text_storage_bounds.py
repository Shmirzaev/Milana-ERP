from app.db.session import SessionLocal
from app.models import AuditLog, Model, ModelColor


def _model_id() -> int:
    with SessionLocal() as db:
        model_id = (
            db.query(Model.id)
            .filter(Model.catalog_scope == "standard")
            .order_by(Model.id)
            .scalar()
        )
        assert model_id is not None
        return int(model_id)


def _counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(ModelColor).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "ModelColor").count(),
        )


def test_model_color_varchar_boundaries_are_accepted(client, auth_headers):
    response = client.post(
        f"/api/models/{_model_id()}/colors",
        json={"color_name": "C" * 64, "color_code": "K" * 16},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text


def test_model_color_overflow_is_rejected_without_writes_and_preserves_precedence(
    client,
    auth_headers,
):
    model_id = _model_id()
    before = _counts()

    for payload in (
        {"color_name": "C" * 65},
        {"color_name": "Black", "color_code": "K" * 17},
    ):
        response = client.post(
            f"/api/models/{model_id}/colors",
            json=payload,
            headers=auth_headers,
        )
        assert response.status_code == 422, response.text
        assert _counts() == before

    unauthenticated = client.post(
        f"/api/models/{model_id}/colors",
        json={"color_name": "C" * 65},
    )
    assert unauthenticated.status_code == 401

    missing_model = client.post(
        "/api/models/2147483647/colors",
        json={"color_name": "C" * 65},
        headers=auth_headers,
    )
    assert missing_model.status_code == 404
    assert _counts() == before

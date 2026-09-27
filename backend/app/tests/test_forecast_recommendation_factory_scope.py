from uuid import uuid4

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, ForecastRecommendation, Model, Role, User


def _factory_user_headers(*, extra_permissions=(), super_admin: bool = False) -> dict[str, str]:
    marker = uuid4().hex[:8]
    permissions = ["forecasting.view", "forecasting.manage"]
    if super_admin:
        permissions.extend(["*", "admin.super"])
    with SessionLocal() as db:
        role = Role(name=f"Forecast recommendation scope {marker}", permissions=permissions)
        db.add(role)
        db.flush()
        user = User(
            name=f"Forecast recommendation scope {marker}",
            email=f"forecast-recommendation-{marker}@example.invalid",
            password_hash="unused-forecast-scope-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=list(extra_permissions),
            is_active=True,
        )
        db.add(user)
        db.commit()
        token = create_access_token(int(user.id), {"factory_code": "MIL"})
    return {"Authorization": f"Bearer {token}"}


def _models_and_recommendations() -> dict[str, int]:
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        models: dict[str, Model] = {}
        for factory_code in ("MIL", "BST", "ECO", None):
            label = factory_code or "UNASSIGNED"
            model = Model(
                code=f"FC-RECOMMENDATION-{label}-{marker}",
                name=f"Forecast recommendation {label} {marker}",
                factory_code=factory_code,
                status="approved",
            )
            db.add(model)
            db.flush()
            models[label] = model
        rows = [
            ForecastRecommendation(
                recommendation_type="branded_stock_production",
                status="open",
                model_id=model.id,
                suggested_quantity=10,
                unit="pcs",
            )
            for model in models.values()
        ]
        db.add_all(rows)
        db.commit()
        return {
            **{factory: int(model.id) for factory, model in models.items()},
            **{f"recommendation_{factory}": int(row.id) for factory, row in zip(models, rows)},
        }


def test_recommendation_reads_include_only_granted_model_factories(client):
    ids = _models_and_recommendations()
    headers = _factory_user_headers(extra_permissions=["factory:ECO:forecasting.view"])

    response = client.get(
        "/api/forecasting/recommendations",
        params={"page": 1, "page_size": 1},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    assert payload["has_more"] is True
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert payload["rows"][0]["model_id"] in {ids["MIL"], ids["ECO"]}


def test_recommendation_create_denies_out_of_scope_and_unattributed_without_writes(client):
    ids = _models_and_recommendations()
    headers = _factory_user_headers(extra_permissions=["factory:ECO:forecasting.manage"])
    with SessionLocal() as db:
        before = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())

    payload = {
        "recommendation_type": "branded_stock_production",
        "suggested_quantity": 5,
        "unit": "pcs",
    }
    denied_factory = client.post(
        "/api/forecasting/recommendations",
        json={**payload, "model_id": ids["BST"]},
        headers=headers,
    )
    denied_unattributed = client.post(
        "/api/forecasting/recommendations",
        json=payload,
        headers=headers,
    )
    allowed_secondary = client.post(
        "/api/forecasting/recommendations",
        json={**payload, "model_id": ids["ECO"]},
        headers=headers,
    )

    assert denied_factory.status_code == 403, denied_factory.text
    assert denied_unattributed.status_code == 403, denied_unattributed.text
    assert allowed_secondary.status_code == 201, allowed_secondary.text
    with SessionLocal() as db:
        after = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
    assert after == (before[0] + 1, before[1] + 1)


def test_recommendation_patch_hides_out_of_scope_and_unattributed_rows(client):
    ids = _models_and_recommendations()
    headers = _factory_user_headers()
    with SessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    denied = client.patch(
        f"/api/forecasting/recommendations/{ids['recommendation_BST']}",
        json={"status": "dismissed"},
        headers=headers,
    )
    denied_unattributed = client.patch(
        f"/api/forecasting/recommendations/{ids['recommendation_UNASSIGNED']}",
        json={"status": "dismissed"},
        headers=headers,
    )
    allowed = client.patch(
        f"/api/forecasting/recommendations/{ids['recommendation_MIL']}",
        json={"status": "dismissed"},
        headers=headers,
    )

    assert denied.status_code == 404, denied.text
    assert denied_unattributed.status_code == 404, denied_unattributed.text
    assert allowed.status_code == 200, allowed.text
    with SessionLocal() as db:
        assert db.get(ForecastRecommendation, ids["recommendation_BST"]).status == "open"
        assert db.get(ForecastRecommendation, ids["recommendation_UNASSIGNED"]).status == "open"
        assert db.query(AuditLog).count() == before_audits + 1


def test_super_admin_recommendation_reads_cover_all_attributed_factories(client):
    ids = _models_and_recommendations()
    headers = _factory_user_headers(super_admin=True)

    response = client.get("/api/forecasting/recommendations", headers=headers)

    assert response.status_code == 200, response.text
    visible = {row["model_id"] for row in response.json()}
    assert visible.issuperset({ids["MIL"], ids["BST"], ids["ECO"]})
    assert ids["UNASSIGNED"] not in visible

from uuid import uuid4

from app.db.session import SessionLocal
from app.models import AuditLog, ForecastRecommendation, Model


def test_forecast_list_projects_malformed_legacy_source_roots_without_rewriting_them(client, auth_headers):
    marker = uuid4().hex[:12]
    sources = (["old", {"kind": "import"}], 7, {"source": "current"})
    with SessionLocal() as db:
        model = Model(
            code=f"FORECAST-LEGACY-{marker}", name="Legacy forecast source",
            factory_code="MIL",
        )
        db.add(model)
        db.flush()
        rows = [ForecastRecommendation(
            recommendation_type="item_reorder", status="open", model_id=model.id,
            suggested_quantity=1, source_json=source,
        ) for source in sources]
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
        before_audits = db.query(AuditLog).count()

    response = client.get("/api/forecasting/recommendations", headers=auth_headers)
    assert response.status_code == 200, response.text
    returned = {row["id"]: row for row in response.json()}
    assert [returned[row_id]["source_json"] for row_id in ids] == [None, None, sources[2]]
    with SessionLocal() as db:
        assert [db.get(ForecastRecommendation, row_id).source_json for row_id in ids] == list(sources)
        assert db.query(AuditLog).count() == before_audits

from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.forecasting import list_forecast_recommendations
from app.db.session import SessionLocal
from app.models import AuditLog, ForecastRecommendation


def _seed_recommendations(count: int) -> tuple[list[int], int]:
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        db.query(ForecastRecommendation).delete(synchronize_session=False)
        rows = [
            ForecastRecommendation(
                recommendation_type="item_reorder",
                status="open",
                suggested_quantity=index + 1,
                unit="kg",
                confidence="medium",
                reason=f"PERF35 forecast {marker} {index}",
                source_json={"marker": marker, "index": index},
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.flush()
        excluded = ForecastRecommendation(
            recommendation_type="item_reorder",
            status="dismissed",
            suggested_quantity=1,
            reason=f"Excluded forecast {marker}",
        )
        db.add(excluded)
        db.commit()
        return [int(row.id) for row in rows], int(excluded.id)


def _read(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_forecast_recommendations(db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_forecast_recommendation_pages_bound_rows_and_preserve_legacy_payload(count):
    created_ids, excluded_id = _seed_recommendations(count)

    page, statements = _read(status="open", page=1, page_size=count)
    legacy, legacy_statements = _read(status="open", page=None, page_size=None)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is False
    assert [row["id"] for row in page["rows"]] == list(reversed(created_ids))
    assert excluded_id not in [row["id"] for row in page["rows"]]
    assert page["rows"] == legacy
    assert len(statements) == 2, statements
    assert len(legacy_statements) == 1, legacy_statements


def test_forecast_recommendation_page_contract_auth_and_no_writes(client, auth_headers):
    created_ids, _ = _seed_recommendations(3)
    with SessionLocal() as db:
        before = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())

    response = client.get(
        "/api/forecasting/recommendations",
        params={"status": "open", "page": 1, "page_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["has_more"] is True
    assert [row["id"] for row in payload["rows"]] == list(reversed(created_ids))[:2]
    assert client.get(
        "/api/forecasting/recommendations",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/forecasting/recommendations",
        params={"page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with SessionLocal() as db:
        after = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
    assert after == before

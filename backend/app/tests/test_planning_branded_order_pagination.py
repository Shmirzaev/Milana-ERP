from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.planning import list_branded_orders
from app.models import BrandedPlanningOrder
from app.tests.conftest import TestSessionLocal


def _seed_orders(count, *, status="open"):
    marker = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        baseline = db.query(BrandedPlanningOrder).filter(BrandedPlanningOrder.status == status).count()
        rows = [
            BrandedPlanningOrder(
                order_no=f"PERF35-BPO-{marker}-{number:04d}",
                ordered_for_type="milana",
                ordered_for_name="Milana",
                status=status,
                notes=f"bounded planning row {number}",
            )
            for number in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return [int(row.id) for row in rows], baseline


def _read(**kwargs):
    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_branded_orders(db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_branded_order_pages_bound_rows_preserve_legacy_payload_and_query_growth(count):
    created_ids, baseline = _seed_orders(count)

    page, statements = _read(status="open", page=1, page_size=count)
    legacy, _ = _read(status="open")

    assert page["total"] == baseline + count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is (baseline > 0)
    assert [row["id"] for row in page["rows"]] == list(reversed(created_ids))
    assert page["rows"] == legacy[:count]
    assert all(row["productions"] == [] for row in page["rows"])
    assert all(row["production_count"] == row["total_quantity"] == 0 for row in page["rows"])
    assert len(statements) == 2, statements


def test_branded_order_page_applies_status_before_count(client, auth_headers):
    created_ids, baseline = _seed_orders(1, status="closed")

    response = client.get(
        "/api/planning/branded-orders",
        params={"status": "closed", "page": 1, "page_size": 1},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == baseline + 1
    assert page["rows"][0]["id"] == created_ids[0]
    assert len(page["rows"]) == 1


def test_branded_order_page_size_is_bounded(client, auth_headers):
    response = client.get(
        "/api/planning/branded-orders",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text

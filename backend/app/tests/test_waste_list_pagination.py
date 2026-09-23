from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.waste import list_waste
from app.db.session import SessionLocal
from app.models import WasteRecord


def _seed_waste(count, *, status="recorded", sellable=False):
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        baseline = db.query(WasteRecord).filter(
            WasteRecord.status == status,
            WasteRecord.sellable.is_(sellable),
        ).count()
        rows = [
            WasteRecord(
                waste_type=f"PERF35-WASTE-{marker}-{number:04d}",
                quantity=number + 1,
                unit="kg",
                reason=f"bounded waste row {number}",
                sellable=sellable,
                estimated_value=number + 0.25,
                status=status,
            )
            for number in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return [int(row.id) for row in rows], baseline


def _read(**kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_waste(db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_waste_pages_bound_rows_preserve_legacy_payload_and_query_growth(count):
    created_ids, baseline = _seed_waste(count)

    page, statements = _read(status="recorded", sellable=False, page=1, page_size=count)
    legacy, _ = _read(status="recorded", sellable=False)

    assert page["total"] == baseline + count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is (baseline > 0)
    assert [row.id for row in page["rows"]] == list(reversed(created_ids))
    assert page["rows"] == legacy[:count]
    assert all(float(row.estimated_value) == 0 for row in page["rows"])
    assert all(float(row.remaining_quantity) == float(row.quantity) for row in page["rows"])
    assert len(statements) == 3, statements
    page_query = next(statement for statement in statements if "from waste_records" in statement and "count(" not in statement)
    assert "created_by" not in page_query
    assert "updated_at" not in page_query
    assert "created_at" in page_query


def test_waste_page_applies_status_and_sellable_before_count(client, auth_headers):
    created_ids, baseline = _seed_waste(1, status="sold", sellable=True)

    response = client.get(
        "/api/waste",
        params={"status": "sold", "sellable": "true", "page": 1, "page_size": 1},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == baseline + 1
    assert page["rows"][0]["id"] == created_ids[0]
    assert page["rows"][0]["status"] == "sold"
    assert page["rows"][0]["sellable"] is True


def test_waste_page_size_is_bounded(client, auth_headers):
    response = client.get(
        "/api/waste",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text

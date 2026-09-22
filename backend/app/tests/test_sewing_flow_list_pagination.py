from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.sewing_flows import list_flows
from app.db.session import SessionLocal
from app.models import SewingFlow


def _factory_user(factory="MIL"):
    return SimpleNamespace(
        role=SimpleNamespace(name=""),
        extra_permissions=["sewing.flows"],
        factory_code=factory,
        session_factory_code=factory,
    )


def _seed_flows(count, *, is_active=True):
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        baseline = db.query(SewingFlow).filter(
            SewingFlow.factory_code == "MIL",
            SewingFlow.is_active.is_(is_active),
        ).count()
        rows = [
            SewingFlow(
                factory_code="MIL",
                code=f"PERF35-{marker}-{number:04d}",
                name=f"Bounded line {marker} {number}",
                capacity_per_day=number + 1,
                is_active=is_active,
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
            payload = list_flows(db, _factory_user(), **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_sewing_flow_pages_bound_rows_preserve_legacy_payload_and_query_growth(count):
    _, baseline = _seed_flows(count)

    page, statements = _read(only_active=True, factory_code="MIL", page=1, page_size=count)
    legacy, _ = _read(only_active=True, factory_code="MIL")

    assert page["total"] == baseline + count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is (baseline > 0)
    assert page["rows"] == legacy[:count]
    assert len(page["rows"]) == count
    assert all(row.factory_code == "MIL" and row.is_active for row in page["rows"])
    assert all(row.active_work_orders == row.planned_units == row.completed_units == 0 for row in page["rows"])
    assert len(statements) == 5, statements
    supporting_queries = statements[2:]
    assert all(" in (" in statement for statement in supporting_queries), statements


def test_sewing_flow_page_applies_active_and_factory_scope_before_count(client, auth_headers):
    created_ids, baseline = _seed_flows(1, is_active=False)

    response = client.get(
        "/api/sewing-flows",
        params={"factory_code": "MIL", "only_active": "false", "page": 1, "page_size": 500},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] >= baseline + 1
    assert any(row["id"] == created_ids[0] for row in page["rows"])
    assert all(row["factory_code"] == "MIL" for row in page["rows"])


def test_sewing_flow_page_size_is_bounded(client, auth_headers):
    response = client.get(
        "/api/sewing-flows",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text

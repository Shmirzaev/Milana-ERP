"""CUT/ECT inbox cards page before expensive card context hydration."""

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event

from app.api.routes import inbox
from app.models import Department, Model, ProductionBatch, ProductionOrder, WorkOrder
from app.tests.conftest import TestSessionLocal, test_engine


def _enable_inbox_access(monkeypatch):
    monkeypatch.setattr(inbox, "require_operational_department_access", lambda *_args: None)
    monkeypatch.setattr(inbox, "user_permissions", lambda _user: ["*"])


def test_cutting_order_page_has_exact_total_and_sql_row_limit(monkeypatch):
    _enable_inbox_access(monkeypatch)
    suffix = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        department = db.query(Department).filter_by(code="CUT").one()
        model = Model(code=f"CUT-PAGE-{suffix}", name="Cutting inbox page model")
        db.add(model)
        db.flush()
        production_order = ProductionOrder(
            production_no=f"CUT-PAGE-{suffix}",
            production_type="client_order",
            model_id=model.id,
            status="new",
            planned_quantity=401,
        )
        db.add(production_order)
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=production_order.id,
                batch_no=f"B{index + 1:04d}",
                batch_index=index + 1,
                planned_quantity=1,
            )
            for index in range(401)
        ]
        db.add_all(batches)
        db.flush()
        db.add_all([
            WorkOrder(
                production_order_id=production_order.id,
                production_batch_id=batch.id,
                department_id=department.id,
                operation="cutting",
                status="pending",
                planned_output_qty=1,
            )
            for batch in batches
        ])
        db.commit()

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            first = inbox.cutting_order_page(db, SimpleNamespace(department_id=None), dept="CUT")
            second = inbox.cutting_order_page(db, SimpleNamespace(department_id=None), dept="CUT", offset=50)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert first["total"] == second["total"] == 401
    assert len(first["rows"]) == len(second["rows"]) == 50
    assert first["has_more"] and second["has_more"]
    assert {row["id"] for row in first["rows"]}.isdisjoint(row["id"] for row in second["rows"])
    assert all(row["production_order_id"] == production_order.id for row in first["rows"])
    work_order_selects = [
        statement for statement in statements
        if " from work_orders " in statement and " join production_orders " in statement
        and " limit ? offset ?" in statement
    ]
    assert len(work_order_selects) == 2
    assert not any(statement.startswith(("insert", "update", "delete")) for statement in statements)


def test_cutting_order_page_preserves_auth_and_legacy_inbox(client, auth_headers):
    path = "/api/inbox/cutting-orders?dept=CUT"
    assert client.get(path).status_code == 401
    assert client.get(f"{path}&limit=101", headers=auth_headers).status_code == 422
    assert client.get(f"{path}&offset=-1", headers=auth_headers).status_code == 422
    assert client.get("/api/inbox/cutting-orders?dept=SEW", headers=auth_headers).status_code == 404
    page = client.get(f"{path}&limit=1", headers=auth_headers)
    assert page.status_code == 200, page.text
    assert page.json()["limit"] == 1
    legacy = client.get("/api/inbox?dept=CUT", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert "cutting_work_orders" in legacy.json()

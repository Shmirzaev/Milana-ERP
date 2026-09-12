from datetime import date, datetime, timezone

from sqlalchemy import event, select

from app.db.base import Base
from app.models import CuttingRecord, Department, Model, PackagingRecord, ProductionOrder, WorkOrder
from app.services.dashboard_overview import overview
from app.tests.conftest import TestSessionLocal


def fingerprint(db):
    return {table.name: sorted(repr(tuple(row)) for row in db.execute(select(table)).all())
            for table in Base.metadata.sorted_tables}


def test_branded_production_without_sales_is_counted_and_read_only():
    with TestSessionLocal() as db:
        before_count = overview(db, date(2026, 1, 1), date(2026, 1, 2))["active_orders"]
        model = db.query(Model).first()
        for status in ("planning", "sewing", "completed", "cancelled"):
            db.add(ProductionOrder(production_no=f"DASH-{status}", production_type="branded_stock",
                                   model_id=model.id, status=status, planned_quantity=120))
        db.commit()
        before = fingerprint(db)
        result = overview(db, date(2026, 1, 1), date(2026, 1, 2))
        assert result["active_orders"] == before_count + 2
        names = {row["order_no"] for row in result["orders"]}
        assert {"DASH-planning", "DASH-sewing"} <= names
        assert not {"DASH-completed", "DASH-cancelled"} & names
        assert sum(result["by_status"].values()) == result["active_orders"]
        assert fingerprint(db) == before


def test_output_business_day_bounds_approval_and_no_double_counting():
    with TestSessionLocal() as db:
        order = ProductionOrder(production_no="DASH-BOUNDARY", production_type="branded_stock",
                                model_id=db.query(Model.id).first()[0], status="cutting", planned_quantity=10)
        db.add(order)
        db.flush()
        wo = WorkOrder(production_order_id=order.id, department_id=db.query(Department.id).first()[0],
                       operation="cutting", status="in_progress")
        db.add(wo)
        db.flush()
        for hour, approved, qty in [(18, "approved", 200), (19, "approved", 10), (20, "pending", 80), (21, "rejected", 60)]:
            db.add(CuttingRecord(work_order_id=wo.id, passed_pieces=qty, approval_status=approved,
                                 created_at=datetime(2020, 1, 1, hour, tzinfo=timezone.utc)))
        db.add(PackagingRecord(work_order_id=wo.id, packed_qty=10,
                               created_at=datetime(2020, 1, 1, 19, tzinfo=timezone.utc)))
        db.add(CuttingRecord(work_order_id=wo.id, passed_pieces=300,
                             created_at=datetime(2020, 1, 2, 19, tzinfo=timezone.utc)))
        db.commit()
        result = overview(db, date(2020, 1, 2), date(2020, 1, 2))
        assert result["totals"] == {"cutting": 10, "printing": 0, "sewing": 0, "packaging": 10}
        assert result["daily"] == [{"date": "2020-01-02", **result["totals"]}]
        empty = overview(db, date(2010, 1, 1), date(2010, 1, 3))
        assert len(empty["daily"]) == 3
        assert all(sum(row[k] for k in empty["totals"]) == 0 for row in empty["daily"])


def test_order_preview_is_bounded_with_complete_totals():
    with TestSessionLocal() as db:
        model_id = db.query(Model.id).first()[0]
        for i in range(105):
            db.add(ProductionOrder(production_no=f"DASH-LIMIT-{i}", production_type="branded_stock",
                                   model_id=model_id, status="planning", planned_quantity=1))
        db.commit()
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.bind, "before_cursor_execute", record)
        try:
            result = overview(db, date(2026, 1, 1), date(2026, 1, 2))
        finally:
            event.remove(db.bind, "before_cursor_execute", record)
        assert len(result["orders"]) == 100
        assert result["active_orders"] >= 105
        assert len(statements) == 8


def test_overview_requires_auth_and_validates_date_range(client, auth_headers):
    url = "/api/dashboard/overview"
    assert client.get(url + "?start=2026-01-01&end=2026-01-02").status_code == 401
    for start, end in [("2026-01-02", "2026-01-01"), ("2020-01-01", "2026-01-01"), ("bad", "2026-01-01")]:
        assert client.get(url, params={"start": start, "end": end}, headers=auth_headers).status_code == 422
    assert client.get(url + "?start=2026-01-01&end=2026-01-02", headers=auth_headers).status_code == 200


def test_overview_rejects_non_management_user(client):
    from app.core.deps import get_current_user
    from app.main import app
    from app.models import Role, User
    user = User(id=9999, name="Production viewer", email="dashboard-test@example.com", is_active=True,
                role=Role(name="Dashboard test", permissions=["planning.production"]))
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        assert client.get("/api/dashboard/overview?start=2026-01-01&end=2026-01-02").status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)

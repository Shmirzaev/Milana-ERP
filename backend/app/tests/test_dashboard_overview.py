from datetime import date, datetime, timezone

from sqlalchemy import event, select

from app.db.base import Base
from app.models import Bundle, CuttingRecord, Department, Model, PackagingRecord, ProductionOrder, SewingRecord, WorkOrder
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
        assert len(statements) == 11


def test_overview_requires_auth_and_validates_date_range(client, auth_headers):
    url = "/api/dashboard/overview"
    assert client.get(url + "?start=2026-01-01&end=2026-01-02").status_code == 401
    for start, end in [("2026-01-02", "2026-01-01"), ("2020-01-01", "2026-01-01"), ("bad", "2026-01-01")]:
        assert client.get(url, params={"start": start, "end": end}, headers=auth_headers).status_code == 422
    assert client.get(url + "?start=2026-01-01&end=2026-01-02", headers=auth_headers).status_code == 200
    assert client.get(url + "?start=2026-01-01&end=2026-01-02&factory=invalid", headers=auth_headers).status_code == 422


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


def test_three_factories_split_routing_and_physical_output():
    with TestSessionLocal() as db:
        model_id = db.query(Model.id).first()[0]
        departments = {row.code: row.id for row in db.query(Department).all()}
        orders = {}

        def order(name, status="sewing", source="standard"):
            result = ProductionOrder(production_no=f"DASH-FACTORY-{name}", production_type="branded_stock",
                                     source_type=source, model_id=model_id, status=status, planned_quantity=100)
            db.add(result)
            db.flush()
            orders[name] = result
            return result

        def bundle(po, factory, status="created"):
            name = f"{po.production_no}-{factory}"
            db.add(Bundle(production_order_id=po.id, model_id=model_id, bundle_no=name, barcode=name,
                          color="test", size="M", quantity=10, sewing_factory_code=factory, status=status))

        def work(po, department, operation="sewing"):
            result = WorkOrder(production_order_id=po.id, department_id=departments[department],
                               operation=operation, status="in_progress")
            db.add(result)
            db.flush()
            return result

        mil = order("MIL")
        bundle(mil, "MIL")
        bst = order("BST")
        bundle(bst, "BST")
        # Stale legacy Milana department must not override routed Besttex bundles.
        work(bst, "MIL")
        eco = order("ECO", source="usluga")
        eco_work = work(eco, "ECO")  # legacy/service order fallback without bundles
        shared = order("SHARED")
        bundle(shared, "MIL")
        bundle(shared, "BST")
        cancelled = order("CANCELLED-BUNDLE")
        bundle(cancelled, "ECO", status="cancelled")
        order("UNASSIGNED", status="planning")
        closed = order("CLOSED", status="completed")
        bundle(closed, "MIL")

        # Milana cutting for a Besttex-routed order remains Milana output.
        cut = work(bst, "CUT", "cutting")
        bst_work = work(bst, "BST")
        stamp = datetime(2020, 2, 1, 8, tzinfo=timezone.utc)
        db.add(CuttingRecord(work_order_id=cut.id, passed_pieces=70, created_at=stamp))
        db.add(SewingRecord(work_order_id=bst_work.id, passed_qty=30, created_at=stamp))
        db.add(SewingRecord(work_order_id=eco_work.id, passed_qty=20, created_at=stamp))
        db.commit()
        before = fingerprint(db)
        results = {code: overview(db, date(2020, 2, 1), date(2020, 2, 1), code) for code in ("ALL", "MIL", "BST", "ECO")}
        names = {code: {row["order_no"] for row in result["orders"] if row["order_no"].startswith("DASH-FACTORY-")}
                 for code, result in results.items()}
        assert names["MIL"] == {mil.production_no, shared.production_no}
        assert names["BST"] == {bst.production_no, shared.production_no}
        assert names["ECO"] == {eco.production_no}
        assert len(names["ALL"]) == 6
        assert results["ALL"]["unassigned_orders"] >= 2
        assert results["MIL"]["totals"]["cutting"] == 70
        assert results["BST"]["totals"]["cutting"] == 0
        assert results["BST"]["totals"]["sewing"] == 30
        assert results["ECO"]["totals"]["sewing"] == 20
        assert results["ALL"]["totals"]["sewing"] == 50
        assert [row["code"] for row in results["ALL"]["factories"]] == ["MIL", "BST", "ECO"]
        for code in ("MIL", "BST", "ECO"):
            comparison = next(row for row in results["ALL"]["factories"] if row["code"] == code)
            assert comparison["active_orders"] == results[code]["active_orders"]
            assert comparison["planned_quantity"] == results[code]["planned_quantity"]
            assert comparison["totals"] == results[code]["totals"]
        shared_row = next(row for row in results["ALL"]["orders"] if row["id"] == shared.id)
        assert shared_row["factories"] == ["MIL", "BST"]
        assert fingerprint(db) == before


def test_sewing_reports_use_report_date_and_factory_without_minting_stage_output():
    from app.models import SewingFlow
    from app.models.sewing_daily_report import SewingDailyReport

    with TestSessionLocal() as db:
        for code, quantity in [("MIL", 120), ("BST", 60), ("ECO", 30)]:
            line = SewingFlow(factory_code=code, code=f"DASH-REPORT-{code}", name=f"Dashboard {code}", is_active=False)
            db.add(line)
            db.flush()
            for day, qty in [(date(2020, 3, 2), quantity), (date(2020, 3, 3), 999)]:
                db.add(SewingDailyReport(report_date=day, sewing_flow_id=line.id, line_code=line.code,
                                        line_name=line.name, sewn_qty=qty, defective_qty=0,
                                        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        db.commit()
        before = fingerprint(db)
        result = overview(db, date(2020, 3, 1), date(2020, 3, 2))
        assert result["sewing_reports"]["totals"] == {"MIL": 120, "BST": 60, "ECO": 30}
        assert result["sewing_reports"]["daily"] == [
            {"date": "2020-03-01", "values": {"MIL": 0, "BST": 0, "ECO": 0}},
            {"date": "2020-03-02", "values": {"MIL": 120, "BST": 60, "ECO": 30}},
        ]
        assert result["totals"] == {"cutting": 0, "printing": 0, "sewing": 0, "packaging": 0}
        for code, quantity in [("MIL", 120), ("BST", 60), ("ECO", 30)]:
            scoped = overview(db, date(2020, 3, 1), date(2020, 3, 2), code)
            assert scoped["sewing_reports"]["totals"][code] == quantity
            assert sum(scoped["sewing_reports"]["totals"].values()) == quantity
            assert scoped["totals"]["sewing"] == 0
        assert fingerprint(db) == before

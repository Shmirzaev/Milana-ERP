"""Record reference batching with real SQLAlchemy queries."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.tests.payroll_isolated_growth_fixture import payroll_isolated_database as payroll_isolated_database
from app.models.people import payroll_service as service
from app.schemas import Employee, PayrollRecord, ProductionOrder, SalesOrder
from app.schemas.order_reference import BusinessOrderAlias


def user():
    return SimpleNamespace(role=SimpleNamespace(name="", permissions=[]), factory_code="MIL", session_factory_code="MIL")


@pytest.mark.parametrize("shared", [False, True])
def test_record_reference_growth_and_snapshot_identity(shared, payroll_isolated_database):
    engine, sessions = payroll_isolated_database
    marker = uuid4().hex[:8]
    counts = []
    with sessions() as db:
        employee = Employee(factory_code="MIL", employee_no=f"REF-{marker}", full_name="Reference employee", status="active")
        db.add(employee)
        db.flush()
        employee_id = employee.id
        orders = []
        for i in range(50):
            if not shared or not orders:
                so = SalesOrder(order_no=f"SO-{marker}-{i}")
                db.add(so)
                db.flush()
                po = ProductionOrder(production_no=f"PO-{marker}-{i}", sales_order_id=so.id, model_id=1, production_type="client_order")
                db.add(po)
                db.flush()
                alias = f"OLD-{marker}-{i}"
                db.add_all([BusinessOrderAlias(namespace="PO", reference=alias, entity_id=po.id, canonical_reference=po.production_no),
                            BusinessOrderAlias(namespace="SO", reference=f"OLD-SO-{marker}-{i}", entity_id=so.id, canonical_reference=so.order_no)])
                orders.append((po.id, so.id, po.production_no, so.order_no, alias))
            po_id, so_id, po_no, so_no, alias = orders[-1]
            db.add(PayrollRecord(factory_code="MIL", dedupe_key=f"{marker}-{i}", employee_id=employee_id,
                production_order_id=po_id, sales_order_id=so_id, production_no=alias, sales_order_no=f"OLD-SO-{marker}-{0 if shared else i}",
                scan_uid=f"scan-{marker}-{i}", raw_work_json={"production_no": alias, "sales_order_no": f"OLD-SO-{marker}-{0 if shared else i}", "scan_uid": alias},
                scanned_at=datetime(2026, 9, 1, tzinfo=timezone.utc), source="growth", status="recorded"))
        db.commit()
    for size in (1, 10, 50):
        statements = []
        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        with sessions() as db:
            event.listen(engine, "before_cursor_execute", capture)
            try:
                rows = service.list_records(db, user(), employee_id=employee_id, limit=size)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            assert len(rows) == size
            for row, index in zip(rows, range(49, 49 - size, -1)):
                order_index = 0 if shared else index
                assert row["production_no"] == f"PO-{marker}-{order_index}"
                assert row["sales_order_no"] == f"SO-{marker}-{order_index}"
                assert row["raw_work_json"] == {
                    "production_no": f"PO-{marker}-{order_index}",
                    "sales_order_no": f"SO-{marker}-{order_index}",
                    "scan_uid": f"OLD-{marker}-{order_index}",
                }
                assert row["scan_uid"] == f"scan-{marker}-{index}"
        counts.append(len(statements))
    assert counts[0] == counts[1] == counts[2], counts


def test_record_ambiguous_alias_refused_without_changing_records(payroll_isolated_database):
    engine, sessions = payroll_isolated_database
    marker = uuid4().hex[:8]
    with sessions() as db:
        employee = Employee(factory_code="MIL", employee_no=f"AMB-{marker}", full_name="Ambiguous employee", status="active")
        db.add(employee)
        db.flush()
        orders = [ProductionOrder(production_no=f"PO-{marker}-{i}", model_id=1, production_type="branded_stock") for i in range(2)]
        db.add_all(orders)
        db.flush()
        alias = f"AMB-{marker}"
        db.add_all(BusinessOrderAlias(namespace=namespace, reference=alias, entity_id=order.id, canonical_reference=order.production_no)
                   for namespace, order in zip(("PO", "PUBLIC_PO"), orders))
        record = PayrollRecord(factory_code="MIL", dedupe_key=f"amb-{marker}", employee_id=employee.id, production_no=alias,
                               scanned_at=datetime(2026, 9, 1, tzinfo=timezone.utc), source="growth", status="recorded")
        db.add(record)
        db.commit()
        employee_id, record_id = employee.id, record.id
    with sessions() as db:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            service.list_records(db, user(), employee_id=employee_id)
        assert error.value.status_code == 409
        assert db.get(PayrollRecord, record_id).production_no == alias


def test_record_reference_chunk_boundary(payroll_isolated_database):
    engine, sessions = payroll_isolated_database
    marker = uuid4().hex[:8]
    with sessions() as db:
        employee = Employee(factory_code="MIL", employee_no=f"BOUND-{marker}", full_name="Boundary employee", status="active")
        db.add(employee)
        db.flush()
        db.add_all(PayrollRecord(factory_code="MIL", dedupe_key=f"bound-{marker}-{i}", employee_id=employee.id,
            production_no=f"manual-{marker}-{i}", scanned_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            source="growth", status="recorded") for i in range(401))
        db.commit()
        employee_id = employee.id
    counts = []
    for size in (400, 401):
        statements = []
        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        with sessions() as db:
            event.listen(engine, "before_cursor_execute", capture)
            try:
                rows = service.list_records(db, user(), employee_id=employee_id, limit=size)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
        assert len(rows) == size
        assert all(row["production_no"].startswith(f"manual-{marker}-") for row in rows)
        counts.append(len(statements))
    assert 0 < counts[1] - counts[0] <= 4, counts


def test_record_literal_reference_and_snapshot_contract(payroll_isolated_database):
    engine, sessions = payroll_isolated_database
    import json

    marker = uuid4().hex[:8]
    po_no, so_no, public_no = f"PO-{marker}", f"SO-{marker}", f"PO-{int(marker, 16) + 10000000}"
    po_alias, so_alias, public_alias = f"OLD-PO-{marker}", f"OLD-SO-{marker}", f"OLD-PUBLIC-{marker}"
    with sessions() as db:
        employee = Employee(factory_code="MIL", employee_no=f"LIT-{marker}", full_name="Literal employee", status="active")
        sales = SalesOrder(order_no=so_no)
        db.add_all([employee, sales])
        db.flush()
        linked = ProductionOrder(production_no=po_no, sales_order_id=sales.id, model_id=1, production_type="client_order")
        public = ProductionOrder(production_no=public_no, model_id=1, production_type="branded_stock")
        db.add_all([linked, public])
        db.flush()
        db.add_all([
            BusinessOrderAlias(namespace="PO", reference=po_alias, entity_id=linked.id, canonical_reference=po_no),
            BusinessOrderAlias(namespace="SO", reference=so_alias, entity_id=sales.id, canonical_reference=so_no),
            BusinessOrderAlias(namespace="PUBLIC_PO", reference=public_alias, entity_id=public.id, canonical_reference=public_no),
        ])
        mw2 = "*".join(["MW2", str(linked.id), po_alias] + ["-"] * 11 + [str(sales.id), so_alias])
        expected_mw2 = "*".join(["MW2", str(linked.id), po_no] + ["-"] * 11 + [str(sales.id), so_no])
        specs = [
            (dict(production_no=po_alias, sales_order_no=so_alias,
                  raw_work_json={"production_no": po_alias, "sales_order_no": so_alias, "scan_uid": po_alias}),
             (po_no, so_no, {"production_no": po_no, "sales_order_no": so_no, "scan_uid": po_alias})),
            (dict(production_no="manual-unknown", sales_order_no=public_alias,
                  raw_work_json=json.dumps({"production_no": "manual-unknown", "sales_order_no": public_alias, "label_id": public_alias})),
             ("manual-unknown", public_no, json.dumps({"production_no": "manual-unknown", "sales_order_no": public_no, "label_id": public_alias}, separators=(",", ":")))),
            (dict(production_order_id=linked.id, sales_order_id=sales.id, production_no="unrelated", sales_order_no=None,
                  raw_work_json={"production_no": "unrelated", "sales_order_no": "unrelated", "scan_uid": po_alias}),
             (po_no, so_no, {"production_no": "unrelated", "sales_order_no": "unrelated", "scan_uid": po_alias})),
            (dict(raw_work_json=mw2), (None, None, expected_mw2)),
            (dict(raw_work_json=None), (None, None, None)),
        ]
        expected = {}
        for index, (fields, values) in enumerate(specs):
            row = PayrollRecord(factory_code="MIL", dedupe_key=f"lit-{marker}-{index}", employee_id=employee.id,
                                scanned_at=datetime(2026, 9, 1, tzinfo=timezone.utc), source="growth", status="recorded", **fields)
            db.add(row)
            db.flush()
            expected[row.id] = values
        db.commit()
        employee_id = employee.id
    with sessions() as db:
        page = service.list_records(db, user(), employee_id=employee_id, page=1, page_size=3)
        rest = service.list_records(db, user(), employee_id=employee_id, page=2, page_size=3)
        assert page["total"] == 5 and page["has_more"] is True
        assert rest["total"] == 5 and rest["has_more"] is False
        rows = page["rows"] + rest["rows"]
        assert [row["id"] for row in rows] == sorted(expected, reverse=True)
        for row in rows:
            assert (row["production_no"], row["sales_order_no"], row["raw_work_json"]) == expected[row["id"]]


def test_record_ambiguous_sales_and_public_alias_refused(payroll_isolated_database):
    engine, sessions = payroll_isolated_database
    from fastapi import HTTPException

    marker = uuid4().hex[:8]
    with sessions() as db:
        employee = Employee(factory_code="MIL", employee_no=f"SAMB-{marker}", full_name="Sales ambiguity", status="active")
        sales = SalesOrder(order_no=f"SO-{marker}")
        public = ProductionOrder(production_no=f"PO-{marker}", model_id=1, production_type="branded_stock")
        db.add_all([employee, sales, public])
        db.flush()
        alias = f"COLLISION-{marker}"
        db.add_all([BusinessOrderAlias(namespace="SO", reference=alias, entity_id=sales.id, canonical_reference=sales.order_no),
                    BusinessOrderAlias(namespace="PUBLIC_PO", reference=alias, entity_id=public.id, canonical_reference=public.production_no)])
        db.add(PayrollRecord(factory_code="MIL", dedupe_key=f"samb-{marker}", employee_id=employee.id,
                             sales_order_no=alias, scanned_at=datetime(2026, 9, 1, tzinfo=timezone.utc), source="growth", status="recorded"))
        db.commit()
        employee_id = employee.id
    with sessions() as db:
        with pytest.raises(HTTPException) as error:
            service.list_records(db, user(), employee_id=employee_id)
        assert (error.value.status_code, error.value.detail) == (409, "Ambiguous sales/factory order reference; provide the production order ID")

from datetime import datetime, timezone
from uuid import uuid4

from app.models import Employee, PayrollRecord, SewingRecord
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_user_with_permissions
from app.tests.test_sewing_actual_output import make_batch


def test_payroll_can_add_see_edit_but_not_delete_or_cross_factory(client, auth_headers):
    payroll = _create_user_with_permissions(client, auth_headers, email="payroll-hr@example.com",
                                            permissions=["payroll.manage", "payroll.view"])
    created = client.post("/api/employees", headers=payroll, json={"full_name": "Payroll Employee", "phone": "12345"})
    assert created.status_code == 201, created.text
    eid = created.json()["id"]
    assert client.get(f"/api/employees/{eid}", headers=payroll).json()["phone"] == "12345"
    edited = client.patch(f"/api/employees/{eid}", headers=payroll, json={"full_name": "Changed Employee", "salary": 5000})
    assert edited.status_code == 200, edited.text
    assert edited.json()["salary"] == 5000
    assert client.delete(f"/api/employees/{eid}", headers=payroll).status_code == 403
    eco = _create_user_with_permissions(client, auth_headers, email="eco-payroll-hr@example.com",
                                       permissions=["payroll.manage"], factory_code="ECO")
    assert client.get(f"/api/employees/{eid}", headers=eco).status_code == 404
    assert client.patch(f"/api/employees/{eid}", headers=eco, json={"full_name": "Cross factory"}).status_code == 404
    viewer = _create_user_with_permissions(client, auth_headers, email="view-payroll-hr@example.com",
                                          permissions=["payroll.view"])
    assert client.post("/api/employees", headers=viewer, json={"full_name": "Unauthorized"}).status_code == 403


def test_report_counts_two_batches_once_despite_operations_and_pagination(client, auth_headers):
    batch_rows = [make_batch(plan=600, cut=600) for _ in range(2)]
    with TestSessionLocal() as db:
        employee = Employee(full_name="Production report team", factory_code="MIL")
        db.add(employee); db.flush(); eid = employee.id
        for po, batch, orders in batch_rows:
            db.add(SewingRecord(work_order_id=orders["sewing"], production_batch_id=batch,
                                input_qty=590, sewn_qty=600, passed_qty=600))
            for operation in ["sew", "press", "control"]:
                db.add(PayrollRecord(factory_code="MIL", employee_id=eid, dedupe_key=uuid4().hex,
                                    production_order_id=po, production_batch_id=batch,
                                    quantity=600, rate_per_piece=1, total_amount=600,
                                    operation_code=operation, scanned_at=datetime.now(timezone.utc)))
        db.commit()
    for view in ("details", "salary"):
        response = client.get(f"/api/payroll/reports/sewing-production?employee_id={eid}&limit=1&report_view={view}", headers=auth_headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert float(data["total_quantity"]) == 3600
        assert float(data["total_product_quantity"]) == 1200
        assert data["total"] == 6


def test_manual_batches_sum_split_work_then_deduplicate_operations(client, auth_headers):
    with TestSessionLocal() as db:
        employee = Employee(full_name="Manual report team", factory_code="MIL")
        db.add(employee); db.flush(); eid = employee.id
        for batch in ["MAN-A", "MAN-B"]:
            for operation, qty in [("sew", 300), ("sew", 300), ("control", 600)]:
                db.add(PayrollRecord(factory_code="MIL", employee_id=eid, dedupe_key=uuid4().hex,
                                    production_no="MANUAL-ORDER", batch_no=batch, model_code="PRODUCT",
                                    quantity=qty, rate_per_piece=1, total_amount=qty,
                                    operation_code=operation, scanned_at=datetime.now(timezone.utc)))
        db.add(PayrollRecord(factory_code="MIL", employee_id=eid, dedupe_key=uuid4().hex,
                            production_no="MANUAL-ORDER", batch_no="MAN-A", model_code="PRODUCT",
                            quantity=600, rate_per_piece=1, total_amount=600, status="voided",
                            operation_code="sew", scanned_at=datetime.now(timezone.utc)))
        db.commit()
    response = client.get(f"/api/payroll/reports/sewing-production?employee_id={eid}&limit=1", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert float(response.json()["total_product_quantity"]) == 1200

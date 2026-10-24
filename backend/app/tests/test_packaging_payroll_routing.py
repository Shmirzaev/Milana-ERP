from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import load_workbook

from app.models import (
    Bundle, Department, Employee, FinishedGoodsStock, PayrollRecord, ProductionOrder,
    SewingAssignment, SewingFlow, SewingRecord, WorkOrder,
)
from app.tests.conftest import TestSessionLocal
from app.tests.test_first_grade_singles import output, create  # noqa: F401
from app.tests.test_package_workflows import package_qr, stock_fingerprint
from app.tests.test_payroll import _create_employee, _create_user_with_permissions
from app.tests.test_payroll_control_confirmation import _issue
from app.tests.test_sewing_actual_output import make_batch


@pytest.mark.parametrize("name", ["Tepa kontrol", "Pass kontrol", "Kontrol tepa", "Tepa Контроль"])
def test_qualified_control_is_ordinary_work_even_with_qc_code(client, auth_headers, name):
    employee = _create_employee(client, auth_headers)
    label = _issue(client, auth_headers, operation_name=name, operation_code="QC", operation_section="control")
    response = client.post("/api/payroll/scan/numeric-work", headers=auth_headers,
                           json={"token": label["qr_token"], "employee_id": employee["id"]})
    assert response.status_code == 201, response.text
    assert response.json()["control_preview"] is None
    assert response.json()["record"]["employee_id"] == employee["id"]
    assert float(response.json()["record"]["total_amount"]) == 3000
    repeat = client.post("/api/payroll/scan/numeric-work", headers=auth_headers,
                         json={"token": label["qr_token"], "employee_id": employee["id"]})
    assert repeat.json()["record"]["id"] == response.json()["record"]["id"]


def test_salary_stays_under_employee_master_for_all_job_lines_and_export(client, auth_headers):
    with TestSessionLocal() as db:
        masters = [Employee(full_name=name, factory_code="MIL") for name in ("Own Master", "Other Master")]
        db.add_all(masters); db.flush()
        worker = Employee(full_name="Cross-line Worker", factory_code="MIL", manager_employee_id=masters[0].id)
        visitor = Employee(full_name="Other Worker", factory_code="MIL", manager_employee_id=masters[1].id)
        db.add_all([worker, visitor]); db.flush()
        for employee, amount, line in [(worker, 100, "OWN"), (worker, 250, "OTHER"), (visitor, 70, "OWN")]:
            db.add(PayrollRecord(factory_code="MIL", employee_id=employee.id, dedupe_key=uuid4().hex,
                                 quantity=1, rate_per_piece=amount, total_amount=amount,
                                 raw_work_json={"sewing_line_code": line}, scanned_at=datetime.now(timezone.utc)))
        db.commit()
        mid, other, wid = masters[0].id, masters[1].id, worker.id
    url = f"/api/payroll/reports/sewing-production?report_view=salary&sewing_line=manager:{mid}"
    report = client.get(url, headers=auth_headers)
    assert report.status_code == 200, report.text
    rows = report.json()["salary_summary"]
    assert len(rows) == 1 and rows[0]["employee_id"] == wid
    assert rows[0]["master_name"] == "Own Master"
    assert float(rows[0]["total_amount"]) == 350 and rows[0]["record_count"] == 2
    assert sum(map(float, rows[0]["daily_amounts"].values())) == 350
    other_report = client.get(url.replace(f"manager:{mid}", f"manager:{other}"), headers=auth_headers).json()
    assert all(row["employee_id"] != wid for row in other_report["salary_summary"])
    options = client.get("/api/payroll/reports/sewing-production/options", headers=auth_headers).json()
    assert any(row["value"] == f"manager:{mid}" for row in options["salary_masters"])
    export = client.get(url.replace("sewing-production?", "sewing-production.xlsx?"), headers=auth_headers)
    assert export.status_code == 200, export.text
    cells = list(load_workbook(BytesIO(export.content)).active.values)
    assert "Own Master" in str(cells) and "Other Worker" not in str(cells)
    eco = _create_user_with_permissions(client, auth_headers, email="salary-eco-scope@example.com",
                                       permissions=["payroll.view"], factory_code="ECO")
    assert client.get(url, headers=eco).status_code == 404


def second_grade(payload, count=3, weight=0.75):
    return {**payload, "stock_kind": "second_grade", "capacity": count, "weight_kg": weight,
            "items": [{**payload["items"][0], "quantity": count}]}


def test_second_grade_count_weight_receipt_labels_and_shared_size_budget(client, auth_headers, output):  # noqa: F811
    response, body = create(client, auth_headers, [second_grade(output)])
    assert response.status_code == 201, response.text
    run = response.json()
    assert client.post("/api/packages/print-runs/create-packages", headers=auth_headers, json=body).json() == run
    package = run["packages"][0]
    assert package["stock_kind"] == "second_grade"
    assert float(package["weight_kg"]) == 0.75
    assert package["quantity"] == 3
    html = client.get(f'/api/packages/print-runs/{run["id"]}/label', headers=auth_headers)
    assert "2-nav" in html.text
    assert create(client, auth_headers, [output, output])[0].status_code == 201
    before = stock_fingerprint()
    assert create(client, auth_headers, [second_grade(output, 1)])[0].status_code in (400, 409)
    normal = {**output, "stock_kind": "standard", "capacity": 1}
    assert create(client, auth_headers, [normal])[0].status_code in (400, 409)
    assert stock_fingerprint() == before
    received = client.post("/api/packages/print-runs/receive", headers=auth_headers,
                           json={"code": package_qr(run["package_ids"][0])})
    assert received.status_code == 200, received.text
    with TestSessionLocal() as db:
        assert sum(row.quantity for row in db.query(FinishedGoodsStock).filter_by(package_id=run["package_ids"][0])) == 3
    model_url = f'/api/packages/warehouse-model/{output["model_id"]}'
    second = client.get(model_url + "?stock_kind=second_grade", headers=auth_headers).json()
    assert second["total"] == 1 and second["packages"][0]["quantity"] == 3
    assert client.get(model_url, headers=auth_headers).json()["total"] == 0
    assert all(row["available"] <= 2 for row in client.get("/api/sales-orders/first-grade-options", headers=auth_headers).json())


@pytest.mark.parametrize("weight", [None, 0, -1])
def test_second_grade_requires_weight_without_minting_stock(client, auth_headers, output, weight):  # noqa: F811
    before = stock_fingerprint()
    response, _ = create(client, auth_headers, [second_grade(output, weight=weight)])
    assert response.status_code == 422, response.text
    assert stock_fingerprint() == before


def routed_order():
    po, batch, works = make_batch()
    with TestSessionLocal() as db:
        flow = db.query(SewingFlow).filter_by(factory_code="MIL").first()
        db.get(WorkOrder, works["sewing"]).sewing_flow_id = flow.id
        assignment = SewingAssignment(work_order_id=works["sewing"], production_batch_id=batch,
                                      sewing_flow_id=flow.id, quantity=225)
        order = db.get(ProductionOrder, po)
        bundle = Bundle(bundle_no=uuid4().hex, barcode=uuid4().hex, production_order_id=po,
                        production_batch_id=batch, model_id=order.model_id, quantity=225, color="White", size="S",
                        current_department_id=db.query(Department.id).filter_by(code="CUT").scalar(),
                        next_department_id=db.query(Department.id).filter_by(code="MIL").scalar(),
                        sewing_factory_code="MIL")
        db.add_all([assignment, bundle]); db.commit()
        return po, batch, works, bundle.id, assignment.id


def test_cutting_can_change_factory_and_unused_assignment_before_output(client, auth_headers):
    po, batch, works, bundle_id, assignment_id = routed_order()
    url = f'/api/work-orders/{works["cutting"]}/sewing-factory'
    cut_user = _create_user_with_permissions(client, auth_headers, email="factory-cutting@example.com",
                                            permissions=["cutting.records"], factory_code="MIL")
    response = client.patch(url, headers=cut_user, json={"sewing_factory_code": "BST"})
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        sewing, packaging = db.get(WorkOrder, works["sewing"]), db.get(WorkOrder, works["packaging"])
        assert db.get(Department, sewing.department_id).code == "BST"
        assert db.get(Department, packaging.department_id).code == "BPK"
        assert sewing.sewing_flow_id is None
        assert db.get(SewingAssignment, assignment_id).status == "cancelled"
        bundle = db.get(Bundle, bundle_id)
        assert bundle.quantity == 225 and bundle.sewing_factory_code == "BST"
        assert db.get(Department, bundle.next_department_id).code == "BST"
        assert db.get(ProductionOrder, po).planned_quantity == 225
    assert client.patch(url, headers=cut_user, json={"sewing_factory_code": "BST"}).json()["changed"] is False
    with TestSessionLocal() as db:
        db.add(SewingRecord(work_order_id=works["sewing"], production_batch_id=batch,
                           input_qty=1, sewn_qty=1, passed_qty=1))
        db.commit()
    assert client.patch(url, headers=cut_user, json={"sewing_factory_code": "MIL"}).status_code == 409


def test_factory_change_requires_cutting_permission_and_factory(client, auth_headers):
    _, _, works, _, _ = routed_order()
    url = f'/api/work-orders/{works["cutting"]}/sewing-factory'
    for permissions, factory in [(["dashboard.view"], "MIL"), (["cutting.records"], "ECO")]:
        headers = _create_user_with_permissions(client, auth_headers, email=f"{uuid4().hex}@example.com",
                                                permissions=permissions, factory_code=factory)
        assert client.patch(url, headers=headers, json={"sewing_factory_code": "BST"}).status_code == 403
    assert client.patch(url, json={"sewing_factory_code": "BST"}).status_code == 401
    assert client.patch(url, headers=auth_headers, json={"sewing_factory_code": "BAD"}).status_code == 422


def test_changed_factory_completes_sewing_to_packaging_handoff(client, auth_headers):
    from app.tests.test_production_flow import _factory_headers
    po, batch, works, bundle_id, _ = routed_order()
    url = f'/api/work-orders/{works["cutting"]}/sewing-factory'
    assert client.patch(url, headers=auth_headers, json={"sewing_factory_code": "BST"}).status_code == 200
    besttex = _factory_headers("BST")
    assert client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=auth_headers).status_code == 403
    received = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=besttex)
    assert received.status_code == 200, received.text
    sewn = client.post("/api/sewing/records", headers=besttex, json={
        "work_order_id": works["sewing"], "production_batch_id": batch,
        "input_qty": 225, "sewn_qty": 225, "passed_qty": 225,
        "size_quantities": [{"size": "S", "quantity": 225}],
    })
    assert sewn.status_code == 201, sewn.text
    assert client.patch(url, headers=auth_headers, json={"sewing_factory_code": "MIL"}).status_code == 409
    packed = client.post("/api/packaging/records", headers=besttex, json={
        "work_order_id": works["packaging"], "production_batch_id": batch,
        "input_qty": 225, "packed_qty": 225, "damaged_qty": 0,
    })
    assert packed.status_code == 201, packed.text
    with TestSessionLocal() as db:
        assert db.get(WorkOrder, works["sewing"]).passed_qty == 225
        assert db.get(WorkOrder, works["packaging"]).passed_qty == 225
        assert db.get(Department, db.get(WorkOrder, works["packaging"]).department_id).code == "BPK"


def test_cancelled_bundle_cannot_restore_previous_factory(client, auth_headers):
    from app.models.bundles_service import sync_textile_departments_for_bundle_route
    po, batch, works, bundle_id, _ = routed_order()
    with TestSessionLocal() as db:
        live = db.get(Bundle, bundle_id)
        cancelled = Bundle(bundle_no=uuid4().hex, barcode=uuid4().hex, production_order_id=po,
                           production_batch_id=batch, model_id=live.model_id, color=live.color,
                           size=live.size, quantity=1, status="cancelled", sewing_factory_code="MIL")
        db.add(cancelled); db.commit(); cancelled_id = cancelled.id
    result = client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory', headers=auth_headers,
                          json={"sewing_factory_code": "BST"})
    assert result.status_code == 200, result.text
    with TestSessionLocal() as db:
        assert sync_textile_departments_for_bundle_route(db, po, batch) == ("BST", "BPK")
        assert db.get(Bundle, cancelled_id).sewing_factory_code == "MIL"
        assert db.get(Department, db.get(WorkOrder, works["sewing"]).department_id).code == "BST"

"""Run established payroll workflows in isolated Eco Cotton and Besttex sessions."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.models import Department, Model, ModelSize, ProductionOrder, WorkOrder
from app.tests import test_payroll as payroll
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("workflow", [
    "test_employee_number_is_printable_and_resolves_for_payroll_scan",
    "test_create_payroll_period",
    "test_bulk_create_records_and_scan_uid_idempotency",
    "test_adjustments_affect_summary_totals",
    "test_paid_record_reversal_posts_one_audited_deduction_to_open_period",
    "test_numeric_work_scan_resolves_and_records_atomically",
    "test_qr_size_batch_delete_requires_every_label_to_be_never_scanned",
    "test_qr_label_edit_keeps_identity_and_split_supersedes_old_qr",
    "test_returned_payroll_qr_can_be_scanned_for_another_employee",
    "test_void_payroll_record",
])
@pytest.mark.parametrize("factory_code", ["ECO", "BST"])
def test_factory_payroll_workflow_preserves_other_factories(client, auth_headers, workflow, factory_code):
    eco_headers = payroll._create_user_with_permissions(
        client, auth_headers, email=f"{factory_code.lower()}.parity.{uuid4().hex}@example.com", factory_code=factory_code,
        permissions=["hr.employees", "payroll.view", "payroll.manage", "payroll.scan", "payroll.approve", "payroll.pay"],
    )

    def other_factories():
        with TestSessionLocal() as db:
            result = {}
            for name in ["employees", "payroll_periods", "payroll_records", "payroll_qr_labels", "payroll_adjustments"]:
                table = Base.metadata.tables[name]
                result[name] = [dict(r) for r in db.execute(select(table).where(table.c.factory_code != factory_code).order_by(table.c.id)).mappings()]
            return result

    before = other_factories()
    getattr(payroll, workflow)(client, eco_headers)
    assert other_factories() == before


def test_eco_payroll_usluga_models_orders_and_rates_are_isolated(client, auth_headers):
    suffix = uuid4().hex[:8]
    eco = payroll._create_user_with_permissions(client, auth_headers,
        email=f"eco.catalog.{suffix}@example.com", factory_code="ECO",
        permissions=["payroll.scan", "payroll.manage", "payroll.view"])
    scanner = payroll._create_user_with_permissions(client, auth_headers,
        email=f"eco.scanner.{suffix}@example.com", factory_code="ECO", permissions=["payroll.scan"])
    from app.tests.test_paid_operation_factory_scope import _operation
    retained = [_operation("mil-keep", "milana"), _operation("bst-keep", "besttex")]
    with TestSessionLocal() as db:
        model = Model(code=f"ECO-PAY-{suffix}", name="Eco payroll model", catalog_scope="usluga", status="approved",
                      details_json={"paid_operations": retained + [_operation("eco-old", "eco_cotton")]})
        db.add(model)
        db.flush()
        db.add(ModelSize(model_id=model.id, size="M"))
        order = ProductionOrder(production_no=f"USL-PAY-{suffix}", source_type="usluga", production_type="service_order",
                                model_id=model.id, status="packaging", planned_quantity=10)
        db.add(order)
        db.flush()
        department = db.query(Department).filter_by(code="ECO").one()
        db.add(WorkOrder(production_order_id=order.id, department_id=department.id, operation="sewing", status="completed", passed_qty=10))
        db.commit()
        mid, oid = model.id, order.id
    detail_url = f"/api/usluga/models/{mid}"
    options = client.get(f"/api/usluga/model-options?search=ECO-PAY-{suffix}", headers=scanner)
    assert options.status_code == 200, options.text
    assert [r["id"] for r in options.json()["items"]] == [mid]
    detail = client.get(detail_url, headers=scanner)
    assert detail.status_code == 200, detail.text
    assert [r["id"] for r in detail.json()["details_json"]["paid_operations"]] == ["eco-old"]
    sizes = client.get(detail_url + "/process-qr-sizes", headers=scanner)
    assert sizes.status_code == 200 and sizes.json()["sizes"] == ["M"]
    tracked = client.get(f"/api/process-tracking?factory=ECO&sewing_completed_only=true&q=USL-PAY-{suffix}", headers=eco)
    assert tracked.status_code == 200, tracked.text
    assert [(r["production_order_id"], r["source_type"]) for r in tracked.json()] == [(oid, "usluga")]
    payload = {"sewing_factory": "eco_cotton", "paid_operations": [_operation("eco-new", "eco_cotton")]}
    assert client.patch(detail_url + "/paid-operations", json=payload, headers=scanner).status_code == 403
    changed = client.patch(detail_url + "/paid-operations", json=payload, headers=eco)
    assert changed.status_code == 200, changed.text
    payload["sewing_factory"] = "milana"
    assert client.patch(detail_url + "/paid-operations", json=payload, headers=eco).status_code == 403
    for url in [detail_url, detail_url + "/process-qr-sizes", "/api/usluga/model-options"]:
        assert client.get(url, headers=auth_headers).status_code == 403
    assert client.patch(detail_url + "/paid-operations", json=payload, headers=auth_headers).status_code == 403
    with TestSessionLocal() as db:
        operations = db.get(Model, mid).details_json["paid_operations"]
        assert [r for r in operations if r["sewingFactory"] != "eco_cotton"] == retained

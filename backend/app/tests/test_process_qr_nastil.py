"""Only finished nastils contribute to Process QR choices and label quantities."""
import pytest

from app.models import Bundle, Department, PayrollQrLabel, ProductionBatch, ProductionOrder, SewingRecord, WorkOrder
from app.tests.conftest import TestSessionLocal


def _order(*, scoped=False, passed=55, failed=3, rejected=2, plan=60, status="in_progress"):
    with TestSessionLocal() as db:
        department = db.query(Department).filter_by(code="SEW").one()
        po = ProductionOrder(production_no="PO-QR-NASTIL", production_type="own_production",
                             model_id=1, status="sewing", planned_quantity=100)
        db.add(po)
        db.flush()
        batches = [ProductionBatch(production_order_id=po.id, batch_no=f"QR-{i}", batch_index=i,
                                   name=f"Nastil {i}", planned_quantity=qty)
                   for i, qty in [(1, plan), (2, 40)]]
        db.add_all(batches)
        db.flush()
        wo = WorkOrder(production_order_id=po.id, department_id=department.id, operation="sewing",
                       status=status, production_batch_id=batches[0].id if scoped else None)
        db.add(wo)
        db.flush()
        other = wo
        if scoped:
            other = WorkOrder(production_order_id=po.id, department_id=department.id, operation="sewing",
                              status="in_progress", production_batch_id=batches[1].id)
            db.add(other)
            db.flush()
        db.add_all([
            SewingRecord(work_order_id=wo.id, production_batch_id=None if scoped else batches[0].id,
                         input_qty=passed + failed + rejected, sewn_qty=passed, passed_qty=passed,
                         failed_qty=failed, rejected_qty=rejected,
                         size_quantities=[{"size": "M", "quantity": passed}]),
            SewingRecord(work_order_id=other.id, production_batch_id=batches[1].id,
                         input_qty=10, sewn_qty=10, passed_qty=10,
                         size_quantities=[{"size": "L", "quantity": 10}]),
        ])
        db.commit()
        return po.id, [b.id for b in batches], wo.id


def _tracked(client, headers, **params):
    response = client.get("/api/process-tracking", headers=headers, params={
        "sewing_completed_only": "true", "include_total": "true", "q": "PO-QR-NASTIL", **params,
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("scoped", [False, True])
def test_finished_nastil_visible_while_sibling_is_in_progress(client, auth_headers, scoped):
    oid, bids, _ = _order(scoped=scoped)
    payload = _tracked(client, auth_headers, page_size=1)
    assert payload["total"] == 1
    row = payload["rows"][0]
    assert row["production_order_id"] == oid
    assert [b["id"] for b in row["batches"]] == [bids[0]]
    assert row["sewing_completed_quantity"] == 55  # defects and sibling's 10 are excluded
    assert row["sewing_unallocated_quantity"] == 0
    assert row["batches"][0]["sewing_sizes"] == [
        {"size": "M", "completed_quantity": 55, "sewing_completed_quantity": 55},
    ]
    assert {s["size"]: s["sewing_completed_quantity"] for s in row["sizes"]} == {"M": 55}
    # Ordinary process tracking must keep every batch and its current progress.
    ordinary = client.get("/api/process-tracking?q=PO-QR-NASTIL", headers=auth_headers)
    assert ordinary.status_code == 200, ordinary.text
    assert [b["id"] for b in ordinary.json()[0]["batches"]] == bids
    assert _tracked(client, auth_headers, page=2, page_size=1)["rows"] == []


@pytest.mark.parametrize("kwargs", [
    {"passed": 54},  # 59/60 final pieces
    {"passed": 0, "failed": 0, "rejected": 0},
    {"plan": 0},
    {"status": "cancelled"},
])
def test_unfinished_or_cancelled_nastils_do_not_appear(client, auth_headers, kwargs):
    _order(**kwargs)
    assert _tracked(client, auth_headers)["total"] == 0


def test_explicit_batch_work_order_closure_allows_short_output(client, auth_headers):
    _, bids, _ = _order(scoped=True, passed=20, failed=0, rejected=0, status="completed")
    row = _tracked(client, auth_headers)["rows"][0]
    assert [b["id"] for b in row["batches"]] == [bids[0]]
    assert row["sewing_completed_quantity"] == 20


def test_revised_output_removes_nastil_until_finished_again(client, auth_headers):
    _, bids, wid = _order()
    assert _tracked(client, auth_headers)["total"] == 1
    with TestSessionLocal() as db:
        record = db.query(SewingRecord).filter_by(work_order_id=wid, production_batch_id=bids[0]).one()
        record.passed_qty -= 1
        db.commit()
    assert _tracked(client, auth_headers)["total"] == 0


def test_completed_other_factory_nastil_does_not_expose_order(client, auth_headers):
    oid, bids, _ = _order()
    with TestSessionLocal() as db:
        for bid, factory in zip(bids, ["BST", "MIL"]):
            db.add(Bundle(production_order_id=oid, production_batch_id=bid,
                          bundle_no=f"QR-FACTORY-{bid}", barcode=f"QR-FACTORY-{bid}",
                          model_id=1, color="white", size="M", quantity=60,
                          sewing_factory_code=factory, status="received_sewing"))
        db.commit()
    assert _tracked(client, auth_headers)["total"] == 0


def test_cutting_sewing_to_qr_handoff_before_whole_order_closure(client, auth_headers):
    from app.tests.test_production_flow import _issue_required_accessories

    response = client.post("/api/planning/create-branded-production", headers=auth_headers, json={
        "production_type": "branded_stock", "model_id": 1, "planned_quantity": 100,
        "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 100}],
        "batches": [{"name": "Nastil 1", "planned_quantity": 60},
                    {"name": "Nastil 2", "planned_quantity": 40}],
    })
    assert response.status_code == 201, response.text
    oid = response.json()["id"]
    po = client.get(f"/api/production-orders/{oid}", headers=auth_headers).json()
    work = {wo["operation"]: wo["id"] for wo in po["work_orders"]}
    bids = [b["id"] for b in po["batches"]]
    for bid, quantity in zip(bids, [60, 40]):
        response = client.post("/api/cutting/records", headers=auth_headers, json={
            "work_order_id": work["cutting"], "production_batch_id": bid,
            "input_quantity": 20, "input_unit": "kg", "cut_pieces": quantity,
            "passed_pieces": quantity, "defective_pieces": 0, "waste_quantity": 0, "waste_unit": "kg",
            "bundles": [{"color": "white", "size": "M", "quantity": quantity, "count": 1}],
        })
        assert response.status_code == 201, response.text
    _issue_required_accessories(client, auth_headers, oid)
    for bid, quantity in zip(bids, [60, 10]):
        response = client.post("/api/sewing/records", headers=auth_headers, json={
            "work_order_id": work["sewing"], "production_batch_id": bid,
            "input_qty": quantity, "sewn_qty": quantity, "passed_qty": quantity,
            "size_quantities": [{"size": "M", "quantity": quantity}],
        })
        assert response.status_code == 201, response.text
    row = _tracked(client, auth_headers, q=po["production_no"])["rows"][0]
    assert [b["id"] for b in row["batches"]] == bids[:1]
    assert row["sewing_completed_quantity"] == 60
    sewing = client.get(f"/api/work-orders/{work['sewing']}", headers=auth_headers).json()
    assert sewing["status"] == "in_progress"
    label = {"label_uid": f"PY:NASTIL:{oid}:{bids[0]}", "payload": "MW2*nastil-test",
             "production_order_id": oid, "production_batch_id": bids[0], "model_id": 1,
             "operation_section": "sewing", "operation_code": "SEW-QR", "operation_name": "Sewing",
             "size": "M", "quantity": row["batches"][0]["sewing_completed_quantity"],
             "rate_per_piece": 250, "currency": "UZS", "copy_index": 1}
    issued = client.post("/api/payroll/qr-labels/issue", headers=auth_headers, json={"labels": [label]})
    assert issued.status_code == 200, issued.text
    assert issued.json()["created_count"] == 1
    with TestSessionLocal() as db:
        saved_label = db.query(PayrollQrLabel).filter_by(label_uid=label["label_uid"]).one()
        assert saved_label.production_batch_id == bids[0]
        assert saved_label.quantity == 60
    repeated = client.post("/api/payroll/qr-labels/issue", headers=auth_headers, json={"labels": [label]})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["created_count"] == 0
    # Finishing the sibling adds only its own output to the combined QR quantity.
    response = client.post("/api/sewing/records", headers=auth_headers, json={
        "work_order_id": work["sewing"], "production_batch_id": bids[1],
        "input_qty": 30, "sewn_qty": 30, "passed_qty": 30,
        "size_quantities": [{"size": "M", "quantity": 30}],
    })
    assert response.status_code == 201, response.text
    row = _tracked(client, auth_headers, q=po["production_no"])["rows"][0]
    assert [b["id"] for b in row["batches"]] == bids
    assert row["sewing_completed_quantity"] == 100

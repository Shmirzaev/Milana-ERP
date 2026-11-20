from datetime import date, datetime, timezone

import pytest

from app.models.department_dashboards_service import BUSINESS_TZ
from app.schemas import Bundle, BundleScanLog, CuttingRecord, Department, ModelBOM, ProductionBatch, SewingFlow, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_department_dashboards import bundle, order
from app.tests.test_direct_packaging import headers


def seed_handoffs(db):
    batches = {}
    for index, factory in enumerate(("BST", "MIL"), 1):
        po, _, record = order(db, f"PO-2026-00200{index}")
        db.query(ModelBOM).filter_by(model_id=po.model_id).delete()
        batch = ProductionBatch(production_order_id=po.id, batch_no=f"200{index}-01", batch_index=1,
                                name=f"Nastil {index}", planned_quantity=30 * index)
        db.add(batch)
        db.flush()
        rec_dept = db.query(Department.id).filter_by(code=factory).scalar()
        work = WorkOrder(production_order_id=po.id, production_batch_id=batch.id,
                         department_id=rec_dept, operation="sewing", status="waiting", planned_output_qty=30 * index)
        db.add(work)
        for label, quantity in (("A", 10 * index), ("B", 20 * index)):
            row = bundle(db, po, record, f"HANDOFF-{factory}-{label}", factory=factory, quantity=quantity, next_dept=factory)
            row.production_batch_id = batch.id
        line = SewingFlow(factory_code=factory, name="Handoff QA", code=f"HANDOFF-{factory}")
        db.add(line)
        db.flush()
        batches[factory] = (batch.id, line.id)
    return batches


def test_storage_dispatch_report_and_real_sewing_acceptance(client, auth_headers):
    with TestSessionLocal.begin() as db:
        batches = seed_handoffs(db)
    day = datetime.now(BUSINESS_TZ).date().isoformat()

    def get(path, params=None):
        result = client.get(f"/api/bundles/{path}", headers=auth_headers, params=params)
        assert result.status_code == 200, result.text
        return result.json()

    stock = get("cutting-storage-by-order")
    assert [(row["factory"], row["pieces"], len(row["orders"])) for row in stock] == [("BST", 30, 1), ("MIL", 60, 1)]
    options = get("cutting-dispatch-options", {"destination_factory": "BST", "q": "2001-01"})
    bid, line = batches["BST"]
    assert [row["id"] for row in options] == [bid]
    assert "Nastil 1" in options[0]["nastil"]
    path = "/api/bundles/cutting-dispatch"
    request = {"production_batch_id": bid, "factory": "BST"}
    wrong = client.post(path, headers=auth_headers, json={**request, "factory": "MIL"})
    assert wrong.status_code == 409
    out_of_scope = client.post(path + "?cutting_department_code=ECT", headers=auth_headers, json=request)
    assert out_of_scope.status_code == 403
    sent = client.post(path, headers=auth_headers, json=request)
    assert sent.status_code == 201, sent.text
    assert sent.json() == {"pieces": 30, "bundles": 2}
    assert client.post(path, headers=auth_headers, json=request).status_code == 409
    assert get("cutting-storage-by-order")[0]["pieces"] == 0
    assert get("cutting-inventory", {"destination_factory": "BST"})["total"] == 0
    assert get("cutting-dispatch-options", {"destination_factory": "BST"}) == []
    pending = get("cutting-handoffs", {"day": "2025-01-01", "pending": "true"})
    assert len(pending) == 1 and pending[0]["factory"] == "BST" and pending[0]["pieces"] == 30
    assert get("cutting-handoffs", {"day": "2025-01-01"}) == []
    with TestSessionLocal.begin() as db:
        rows = db.query(Bundle).filter_by(production_batch_id=bid).all()
        assert all(row.status == "sent_to_sewing" and row.current_department_id is None for row in rows)
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_([row.id for row in rows]),
                                             BundleScanLog.scan_type == "sent_sewing").count() == 2
        cutting_work_id = db.get(CuttingRecord, rows[0].cutting_record_id).work_order_id
    delete = client.delete(f"/api/work-orders/{cutting_work_id}/batches/{bid}", headers=auth_headers)
    assert delete.status_code == 409
    assert "sent to Sewing" in delete.json()["detail"]
    accept = f"/api/bundles/sewing-batches/{bid}/accept"
    assert client.post(accept, headers=auth_headers, json={"sewing_flow_id": line}).status_code == 403
    accepted = client.post(accept, headers=headers("BST"), json={"sewing_flow_id": line})
    assert accepted.status_code == 200, accepted.text
    assert get("cutting-handoffs", {"day": day, "pending": "true"}) == []
    daily, = get("cutting-handoffs", {"day": day})
    assert daily["pieces"] == daily["received_pieces"] == 30
    assert daily["last_received_at"] is not None
    with TestSessionLocal.begin() as db:
        db.query(Bundle).filter_by(production_batch_id=bid).update({Bundle.quantity: 11})
    report = client.get("/api/bundles/cutting-handoffs/export.csv", headers=auth_headers, params={"day": day})
    assert report.status_code == 200 and "attachment" in report.headers["content-disposition"]
    assert "Nastil 1,Besttex,30,30,0" in report.text


@pytest.mark.parametrize("blocked", ["printing", "unapproved"])
def test_dispatch_rejects_an_entire_nastil_if_one_label_is_ineligible(client, auth_headers, blocked):
    with TestSessionLocal.begin() as db:
        bid, _ = seed_handoffs(db)["BST"]
        row = db.query(Bundle).filter_by(production_batch_id=bid).first()
        if blocked == "printing":
            row.next_department_id = db.query(Department.id).filter_by(code="PRT").scalar()
        else:
            db.get(CuttingRecord, row.cutting_record_id).approval_status = "pending"
    result = client.post("/api/bundles/cutting-dispatch", headers=auth_headers,
                         json={"factory": "BST", "production_batch_id": bid})
    assert result.status_code == 409
    with TestSessionLocal() as db:
        assert db.query(Bundle).filter_by(production_batch_id=bid, status="created").count() == 2


def test_dispatch_groups_by_tashkent_day_and_deduplicates_scans(client, auth_headers):
    with TestSessionLocal.begin() as db:
        bid, _ = seed_handoffs(db)["BST"]
        row = db.query(Bundle).filter_by(production_batch_id=bid).first()
        row.status = "sent_to_sewing"
        target_id = db.query(Department.id).filter_by(code="BST").scalar()
        stamp = datetime(2026, 1, 1, 19, 30, tzinfo=timezone.utc)
        db.add_all([BundleScanLog(bundle_id=row.id, to_department_id=target_id, scan_type="sent_sewing",
                                  scanned_at=stamp) for _ in range(2)])
    for day, expected in ((date(2026, 1, 1), []), (date(2026, 1, 2), [10])):
        report = client.get("/api/bundles/cutting-handoffs", headers=auth_headers, params={"day": day})
        assert report.status_code == 200, report.text
        assert [row["pieces"] for row in report.json()] == expected

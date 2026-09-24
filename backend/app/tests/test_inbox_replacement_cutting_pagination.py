from uuid import uuid4

import pytest

from app.models import (
    Department,
    Model,
    ProductionOrder,
    SewingRecord,
    SewingReplacementRequest,
    WorkOrder,
)
from app.tests.conftest import TestSessionLocal


def _replacement_requests(count: int) -> tuple[list[int], list[int]]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        cutting = db.query(Department).filter(Department.code == "CUT").one()
        sewing = db.query(Department).filter(Department.code == "SEW").one()
        model = Model(code=f"INBOX-REPL-{marker}", name="Inbox replacement pagination")
        db.add(model)
        db.flush()
        request_ids = []
        cutting_work_order_ids = []
        for index in range(count):
            order = ProductionOrder(
                production_no=f"INBOX-REPL-{marker}-{index:04d}",
                production_type="branded_stock",
                model_id=model.id,
                status="sewing",
                planned_quantity=1,
            )
            db.add(order)
            db.flush()
            cutting_work_order = WorkOrder(
                production_order_id=order.id,
                department_id=cutting.id,
                operation="cutting",
                status="waiting",
                planned_input_qty=1,
                planned_output_qty=1,
            )
            sewing_work_order = WorkOrder(
                production_order_id=order.id,
                department_id=sewing.id,
                operation="sewing",
                status="in_progress",
                planned_input_qty=1,
                planned_output_qty=1,
            )
            db.add_all([cutting_work_order, sewing_work_order])
            db.flush()
            sewing_record = SewingRecord(
                work_order_id=sewing_work_order.id,
                production_batch_id=None,
                input_qty=1,
                sewn_qty=1,
                passed_qty=0,
                failed_qty=1,
                rework_qty=0,
                rejected_qty=0,
                defect_reason="pagination fixture",
                line_name="Line 1",
            )
            db.add(sewing_record)
            db.flush()
            request = SewingReplacementRequest(
                production_order_id=order.id,
                sewing_work_order_id=sewing_work_order.id,
                cutting_work_order_id=cutting_work_order.id,
                production_batch_id=None,
                sewing_record_id=sewing_record.id,
                requested_qty=1,
                cut_qty=0,
                replaced_qty=0,
                status="waiting_cutting",
                defect_reason="pagination fixture",
            )
            db.add(request)
            db.flush()
            request_ids.append(int(request.id))
            cutting_work_order_ids.append(int(cutting_work_order.id))
        db.commit()
        return request_ids, cutting_work_order_ids


@pytest.mark.parametrize("request_count", [1, 50, 401])
def test_replacement_cutting_opt_in_page_has_exact_total_and_legacy_parity(
    client,
    auth_headers,
    request_count,
):
    expected_ids, cutting_work_order_ids = _replacement_requests(request_count)
    first = client.get(
        "/api/inbox?dept=CUT&replacement_cutting_limit=50&replacement_cutting_offset=0",
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    first_ids = [row["id"] for row in first_body["replacement_cutting_work"]]
    assert first_body["replacement_cutting_work_total"] == request_count
    assert first_body["replacement_cutting_work_has_more"] is (request_count > 50)
    assert first_ids == expected_ids[:50]

    second = client.get(
        "/api/inbox/replacement-cutting?dept=CUT&limit=50&offset=50",
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["total"] == request_count
    assert second_body["has_more"] is (request_count > 100)
    assert [row["id"] for row in second_body["rows"]] == expected_ids[50:100]

    legacy = client.get("/api/inbox?dept=CUT", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    legacy_body = legacy.json()
    assert [row["id"] for row in legacy_body["replacement_cutting_work"]] == expected_ids
    assert legacy_body["replacement_cutting_work_total"] == request_count

    affected_work_order_ids = set(cutting_work_order_ids)
    assert not affected_work_order_ids.intersection(
        row["id"] for row in first_body["pending_work_orders"]
    )
    assert not affected_work_order_ids.intersection(
        row["id"] for row in first_body["in_progress_work_orders"]
    )
    if request_count == 401:
        assert len(first_ids) == 50
        assert len(first_body["replacement_cutting_work"]) < first_body["replacement_cutting_work_total"]


def test_replacement_cutting_page_requires_auth_and_caps_page_size(
    client,
    auth_headers,
    monkeypatch,
):
    assert client.get("/api/inbox/replacement-cutting?dept=CUT").status_code == 401
    assert client.get(
        "/api/inbox/replacement-cutting?dept=CUT&limit=101",
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/inbox/replacement-cutting?dept=ECT",
        headers=auth_headers,
    ).status_code == 403

    from app.api.routes import inbox

    monkeypatch.setattr(inbox, "require_operational_department_access", lambda *_args: None)
    monkeypatch.setattr(inbox, "user_permissions", lambda _user: [])
    denied = client.get("/api/inbox/replacement-cutting?dept=CUT", headers=auth_headers)
    assert denied.status_code == 403

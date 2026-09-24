from uuid import uuid4

import pytest

from app.models import (
    Bundle,
    Department,
    Model,
    ProductionBatch,
    ProductionOrder,
    SewingRecord,
    SewingReplacementRequest,
    WorkOrder,
)
from app.tests.conftest import TestSessionLocal


def _replacement_requests(count: int) -> list[int]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        sewing = db.query(Department).filter(Department.code == "SEW").one()
        model = Model(code=f"INBOX-RSEW-{marker}", name="Replacement sewing pagination")
        db.add(model)
        db.flush()
        request_ids = []
        for index in range(count):
            order = ProductionOrder(
                production_no=f"INBOX-RSEW-{marker}-{index:04d}",
                production_type="branded_stock",
                model_id=model.id,
                status="sewing",
                planned_quantity=1,
            )
            db.add(order)
            db.flush()
            work_order = WorkOrder(
                production_order_id=order.id,
                department_id=sewing.id,
                operation="sewing",
                status="in_progress",
                planned_input_qty=1,
                planned_output_qty=1,
            )
            db.add(work_order)
            db.flush()
            record = SewingRecord(
                work_order_id=work_order.id,
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
            db.add(record)
            db.flush()
            request = SewingReplacementRequest(
                production_order_id=order.id,
                sewing_work_order_id=work_order.id,
                cutting_work_order_id=None,
                production_batch_id=None,
                sewing_record_id=record.id,
                requested_qty=1,
                cut_qty=1,
                replaced_qty=0,
                status="waiting_sewing",
                defect_reason="pagination fixture",
            )
            db.add(request)
            db.flush()
            request_ids.append(int(request.id))
        db.commit()
        return request_ids


@pytest.mark.parametrize("request_count", [1, 50, 401])
def test_replacement_sewing_page_has_exact_total_stable_order_and_legacy_parity(
    client,
    auth_headers,
    request_count,
):
    expected_ids = _replacement_requests(request_count)
    first = client.get(
        "/api/inbox/replacement-sewing?dept=SEW&limit=50&offset=0",
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    first_ids = [row["id"] for row in first_body["rows"]]
    assert first_body["total"] == request_count
    assert first_body["has_more"] is (request_count > 50)
    assert first_ids == expected_ids[:50]

    second = client.get(
        "/api/inbox/replacement-sewing?dept=SEW&limit=50&offset=50",
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["total"] == request_count
    assert second.json()["has_more"] is (request_count > 100)
    assert [row["id"] for row in second.json()["rows"]] == expected_ids[50:100]

    opt_out = client.get(
        "/api/inbox?dept=SEW&include_replacement_sewing=false",
        headers=auth_headers,
    )
    assert opt_out.status_code == 200, opt_out.text
    assert opt_out.json()["replacement_sewing_work"] == []
    assert opt_out.json()["replacement_sewing_work_total"] is None

    legacy = client.get("/api/inbox?dept=SEW", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert [row["id"] for row in legacy.json()["replacement_sewing_work"]] == expected_ids
    assert legacy.json()["replacement_sewing_work_total"] == request_count


def test_replacement_sewing_page_preserves_factory_alias_and_mixed_factory_filtering(
    client,
    auth_headers,
    monkeypatch,
):
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        sewing = db.query(Department).filter(Department.code == "SEW").one()
        model = Model(code=f"INBOX-RSEW-FILTER-{marker}", name="Factory filter parity")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"INBOX-RSEW-FILTER-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="sewing",
            planned_quantity=2,
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id,
            batch_no=f"B-{marker}",
            batch_index=1,
            planned_quantity=2,
        )
        db.add(batch)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            production_batch_id=batch.id,
            department_id=sewing.id,
            operation="sewing",
            status="in_progress",
            planned_input_qty=2,
            planned_output_qty=2,
        )
        db.add(work_order)
        db.flush()
        record = SewingRecord(
            work_order_id=work_order.id,
            production_batch_id=batch.id,
            input_qty=1,
            sewn_qty=0,
            passed_qty=0,
            failed_qty=1,
            rework_qty=0,
            rejected_qty=0,
            defect_reason="factory filter fixture",
            line_name="Line 1",
        )
        db.add(record)
        db.flush()
        request = SewingReplacementRequest(
            production_order_id=order.id,
            sewing_work_order_id=work_order.id,
            production_batch_id=batch.id,
            sewing_record_id=record.id,
            requested_qty=1,
            cut_qty=1,
            replaced_qty=0,
            status="waiting_sewing",
        )
        db.add(request)
        db.add(
            Bundle(
                bundle_no=f"BND-RSEW-{marker}",
                barcode=f"BC-RSEW-{marker}",
                production_order_id=order.id,
                production_batch_id=batch.id,
                model_id=model.id,
                color="blue",
                size="M",
                quantity=1,
                sewing_factory_code="BTX",
                status="sent_to_sewing",
            )
        )
        mixed_model = Model(code=f"INBOX-RSEW-MIXED-{marker}", name="Mixed factory parity")
        db.add(mixed_model)
        db.flush()
        mixed_order = ProductionOrder(
            production_no=f"INBOX-RSEW-MIXED-{marker}",
            production_type="branded_stock",
            model_id=mixed_model.id,
            status="sewing",
            planned_quantity=2,
        )
        db.add(mixed_order)
        db.flush()
        mixed_batch = ProductionBatch(
            production_order_id=mixed_order.id,
            batch_no=f"BM-{marker}",
            batch_index=1,
            planned_quantity=2,
        )
        db.add(mixed_batch)
        db.flush()
        mixed_work_order = WorkOrder(
            production_order_id=mixed_order.id,
            production_batch_id=mixed_batch.id,
            department_id=sewing.id,
            operation="sewing",
            status="in_progress",
            planned_input_qty=2,
            planned_output_qty=2,
        )
        db.add(mixed_work_order)
        db.flush()
        mixed_record = SewingRecord(
            work_order_id=mixed_work_order.id,
            production_batch_id=mixed_batch.id,
            input_qty=1,
            sewn_qty=0,
            passed_qty=0,
            failed_qty=1,
            rework_qty=0,
            rejected_qty=0,
            defect_reason="mixed factory filter fixture",
            line_name="Line 2",
        )
        db.add(mixed_record)
        db.flush()
        mixed_request = SewingReplacementRequest(
            production_order_id=mixed_order.id,
            sewing_work_order_id=mixed_work_order.id,
            production_batch_id=mixed_batch.id,
            sewing_record_id=mixed_record.id,
            requested_qty=1,
            cut_qty=1,
            replaced_qty=0,
            status="waiting_sewing",
        )
        db.add(mixed_request)
        db.add_all([
            Bundle(
                bundle_no=f"BND-RSEW-MIXED-BST-{marker}",
                barcode=f"BC-RSEW-MIXED-BST-{marker}",
                production_order_id=mixed_order.id,
                production_batch_id=mixed_batch.id,
                model_id=mixed_model.id,
                color="blue",
                size="M",
                quantity=1,
                sewing_factory_code="BTX",
                status="sent_to_sewing",
            ),
            Bundle(
                bundle_no=f"BND-RSEW-MIXED-MIL-{marker}",
                barcode=f"BC-RSEW-MIXED-MIL-{marker}",
                production_order_id=mixed_order.id,
                production_batch_id=mixed_batch.id,
                model_id=mixed_model.id,
                color="blue",
                size="L",
                quantity=1,
                sewing_factory_code="SML",
                status="sent_to_sewing",
            ),
        ])
        non_sewing_model = Model(
            code=f"INBOX-RSEW-NONSEW-{marker}",
            name="Non-sewing linked work-order parity",
        )
        db.add(non_sewing_model)
        db.flush()
        non_sewing_order = ProductionOrder(
            production_no=f"INBOX-RSEW-NONSEW-{marker}",
            production_type="branded_stock",
            model_id=non_sewing_model.id,
            status="sewing",
            planned_quantity=1,
        )
        db.add(non_sewing_order)
        db.flush()
        non_sewing_work_order = WorkOrder(
            production_order_id=non_sewing_order.id,
            department_id=sewing.id,
            operation="cutting",
            status="in_progress",
            planned_input_qty=1,
            planned_output_qty=1,
        )
        db.add(non_sewing_work_order)
        db.flush()
        non_sewing_record = SewingRecord(
            work_order_id=non_sewing_work_order.id,
            production_batch_id=None,
            input_qty=1,
            sewn_qty=0,
            passed_qty=0,
            failed_qty=1,
            rework_qty=0,
            rejected_qty=0,
            defect_reason="non-sewing operation filter fixture",
            line_name="Line 3",
        )
        db.add(non_sewing_record)
        db.flush()
        non_sewing_request = SewingReplacementRequest(
            production_order_id=non_sewing_order.id,
            sewing_work_order_id=non_sewing_work_order.id,
            sewing_record_id=non_sewing_record.id,
            requested_qty=1,
            cut_qty=1,
            replaced_qty=0,
            status="waiting_sewing",
        )
        db.add(non_sewing_request)
        db.add(
            Bundle(
                bundle_no=f"BND-RSEW-NONSEW-{marker}",
                barcode=f"BC-RSEW-NONSEW-{marker}",
                production_order_id=non_sewing_order.id,
                model_id=non_sewing_model.id,
                color="blue",
                size="M",
                quantity=1,
                sewing_factory_code="BTX",
                status="sent_to_sewing",
            )
        )
        db.commit()
        expected_id = int(request.id)
        mixed_id = int(mixed_request.id)
        non_sewing_id = int(non_sewing_request.id)

    from app.api.routes import inbox

    monkeypatch.setattr(inbox, "require_operational_department_access", lambda *_args: None)
    besttex = client.get("/api/inbox/replacement-sewing?dept=BST", headers=auth_headers)
    milana = client.get("/api/inbox/replacement-sewing?dept=MIL", headers=auth_headers)
    generic_sewing = client.get("/api/inbox/replacement-sewing?dept=SEW", headers=auth_headers)
    assert besttex.status_code == 200, besttex.text
    assert milana.status_code == 200, milana.text
    besttex_rows = besttex.json()["rows"]
    assert expected_id in {row["id"] for row in besttex_rows}
    assert next(row for row in besttex_rows if row["id"] == expected_id)["textile_code"] == "BST"
    assert mixed_id not in {row["id"] for row in besttex_rows}
    assert non_sewing_id not in {row["id"] for row in besttex_rows}
    assert expected_id not in {row["id"] for row in milana.json()["rows"]}
    assert mixed_id not in {row["id"] for row in milana.json()["rows"]}
    assert non_sewing_id in {row["id"] for row in generic_sewing.json()["rows"]}


def test_replacement_sewing_page_authorization_and_bounds(client, auth_headers, monkeypatch):
    assert client.get("/api/inbox/replacement-sewing?dept=SEW").status_code == 401
    assert client.get(
        "/api/inbox/replacement-sewing?dept=SEW&limit=101",
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/inbox/replacement-sewing?dept=CUT",
        headers=auth_headers,
    ).status_code == 404

    from app.api.routes import inbox

    monkeypatch.setattr(inbox, "require_operational_department_access", lambda *_args: None)
    monkeypatch.setattr(inbox, "user_permissions", lambda _user: [])
    denied = client.get("/api/inbox/replacement-sewing?dept=SEW", headers=auth_headers)
    assert denied.status_code == 403


from uuid import uuid4

import pytest

from app.schemas import Bundle, CuttingRecord, Department, ProductionBatch, SewingRecord, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_packaging_payroll_routing import routed_order


def mixed_order():
    po, first, works, first_bundle, _ = routed_order()
    with TestSessionLocal() as db:
        db.add(SewingRecord(work_order_id=works["sewing"], production_batch_id=first,
                           input_qty=225, sewn_qty=225, passed_qty=225))
        sewing = db.get(WorkOrder, works["sewing"])
        sewing.actual_input_qty = sewing.actual_output_qty = sewing.passed_qty = 225
        for operation in ("sewing", "packaging"):
            db.get(WorkOrder, works[operation]).planned_input_qty = 425
            db.get(WorkOrder, works[operation]).planned_output_qty = 425
        live = db.get(Bundle, first_bundle)
        live.status = "received_sewing"
        ids = []
        for index in (2, 3):
            batch = ProductionBatch(production_order_id=po, batch_index=index,
                batch_no=f"{po}-{index}", name=f"Nastil {index}", planned_quantity=100)
            db.add(batch); db.flush(); ids.append(batch.id)
            db.add(CuttingRecord(work_order_id=works["cutting"], production_batch_id=batch.id,
                                cut_pieces=100, passed_pieces=100, input_quantity=0))
            db.add(Bundle(bundle_no=uuid4().hex, barcode=uuid4().hex, production_order_id=po,
                production_batch_id=batch.id, model_id=live.model_id, color="White", size="S", quantity=100,
                sewing_factory_code="MIL", status="received_sewing", current_department_id=live.current_department_id,
                next_department_id=live.next_department_id))
        db.commit()
        return po, first, works, first_bundle, ids


def test_select_two_nastils_preserves_first_and_completes_besttex_handoff(client, auth_headers):
    from app.tests.test_production_flow import _factory_headers
    po, first, works, bundle, ids = mixed_order()
    url = f'/api/work-orders/{works["cutting"]}/sewing-factory'
    response = client.patch(url, headers=auth_headers, json={"sewing_factory_code": "BST", "production_batch_ids": ids})
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True
    assert client.patch(url, headers=auth_headers, json={"sewing_factory_code": "BST", "production_batch_ids": ids}).json()["changed"] is False
    with TestSessionLocal() as db:
        assert db.get(Bundle, bundle).sewing_factory_code == "MIL"
        assert db.get(WorkOrder, works["sewing"]).passed_qty == 225
        assert db.get(WorkOrder, works["sewing"]).actual_input_qty == 225
        assert db.query(SewingRecord).filter_by(production_batch_id=first).one().passed_qty == 225
        assert sum(w.planned_output_qty for w in db.query(WorkOrder).filter_by(production_order_id=po, operation="sewing")) == 425
        new_works = {w.production_batch_id: w.id for w in db.query(WorkOrder).filter(
            WorkOrder.production_order_id == po, WorkOrder.operation == "sewing", WorkOrder.production_batch_id.in_(ids))}
        assert len(new_works) == 2
    original_progress = client.get(f'/api/work-orders/{works["sewing"]}/sewing-batch-progress', headers=auth_headers).json()
    assert [r["id"] for r in original_progress["items"]] == [first]
    besttex = _factory_headers("BST")
    for bid, wid in new_works.items():
        payload = {"work_order_id": wid, "production_batch_id": bid, "input_qty": 100, "sewn_qty": 100,
                   "passed_qty": 100, "size_quantities": [{"size": "S", "quantity": 100}]}
        assert client.post('/api/sewing/records', headers=auth_headers, json=payload).status_code == 403
        assert client.post('/api/sewing/records', headers=auth_headers, json={**payload, "work_order_id": works["sewing"]}).status_code == 409
        sewn = client.post('/api/sewing/records', headers=besttex, json=payload)
        assert sewn.status_code == 201, sewn.text
        with TestSessionLocal() as db:
            packaging = db.query(WorkOrder).filter_by(production_order_id=po, production_batch_id=bid, operation="packaging").one()
            pwid = packaging.id
            assert db.get(Department, packaging.department_id).code == "BPK"
        packed = client.post('/api/packaging/records', headers=besttex, json={"work_order_id": pwid,
            "production_batch_id": bid, "input_qty": 100, "packed_qty": 100, "damaged_qty": 0})
        assert packed.status_code == 201, packed.text


@pytest.mark.parametrize("selection", ["sewn", "foreign", "duplicate", "empty"])
def test_invalid_selection_cannot_move_history(client, auth_headers, selection):
    _, first, works, bundle, ids = mixed_order()
    choices = {"sewn": [first], "foreign": [999999], "duplicate": [ids[0], ids[0]], "empty": []}
    response = client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory', headers=auth_headers,
        json={"sewing_factory_code": "BST", "production_batch_ids": choices[selection]})
    assert response.status_code in {404, 409, 422}, response.text
    with TestSessionLocal() as db:
        assert db.get(Bundle, bundle).sewing_factory_code == "MIL"


def test_later_cutting_does_not_duplicate_dedicated_plans(client, auth_headers):
    from app.models.workflow_service import propagate_cutting_plan_from_output
    po, _, works, _, ids = mixed_order()
    result = client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory', headers=auth_headers,
        json={"sewing_factory_code": "BST", "production_batch_ids": ids})
    assert result.status_code == 200, result.text
    with TestSessionLocal() as db:
        cut = db.get(WorkOrder, works["cutting"])
        cut.passed_qty = cut.actual_output_qty = 525
        propagate_cutting_plan_from_output(db, cut)
        for operation in ("sewing", "packaging"):
            rows = db.query(WorkOrder).filter_by(production_order_id=po, operation=operation).all()
            assert sum(w.planned_output_qty for w in rows) == 525


def test_transferring_all_nastils_retires_empty_shared_and_denies_unbatched_output(client, auth_headers):
    po, batch, works, _, _ = routed_order()
    result = client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory', headers=auth_headers,
        json={"sewing_factory_code": "BST", "production_batch_ids": [batch]})
    assert result.status_code == 200, result.text
    response = client.post('/api/sewing/records', headers=auth_headers, json={
        "work_order_id": works["sewing"], "input_qty": 225, "sewn_qty": 225, "passed_qty": 225})
    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        for operation in ("sewing", "packaging"):
            assert db.get(WorkOrder, works[operation]).status == "completed"


@pytest.mark.parametrize("reverse", [False, True])
def test_receiving_preserves_exclusive_input_for_both_factories(client, auth_headers, reverse):
    from app.tests.test_production_flow import _factory_headers
    po, first, works, bundle, ids = mixed_order()
    with TestSessionLocal() as db:
        for b in db.query(Bundle).filter_by(production_order_id=po):
            b.status = "created"
        db.commit()
    result = client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory', headers=auth_headers,
        json={"sewing_factory_code": "BST", "production_batch_ids": ids})
    assert result.status_code == 200, result.text
    with TestSessionLocal() as db:
        bundles = db.query(Bundle).filter_by(production_order_id=po).order_by(Bundle.id).all()
        sequence = [(b.id, b.sewing_factory_code) for b in bundles]
    if reverse: sequence.reverse()
    for bid, factory in sequence:
        response = client.post(f'/api/bundles/{bid}/receive-sewing', headers=auth_headers if factory == "MIL" else _factory_headers(factory))
        assert response.status_code == 200, response.text
        with TestSessionLocal() as db:
            assert db.get(WorkOrder, works["sewing"]).actual_input_qty == 225


def test_dedicated_sewing_counts_printing_rejects_from_shared_printing_work(client, auth_headers):
    from app.schemas import PrintingRecord
    from app.models.workflow_service import _complete_if_done
    po, batch, works, _, _ = routed_order()
    result = client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory', headers=auth_headers,
        json={"sewing_factory_code": "BST", "production_batch_ids": [batch]})
    assert result.status_code == 200, result.text
    with TestSessionLocal() as db:
        printing = WorkOrder(production_order_id=po, operation="printing", department_id=db.query(Department.id).filter_by(code="PRT").scalar(),
            planned_output_qty=225, passed_qty=215, failed_qty=10, status="completed")
        db.add(printing); db.flush()
        db.add(PrintingRecord(work_order_id=printing.id, production_batch_id=batch,
            input_qty=225, printed_qty=225, passed_qty=215, rejected_qty=10))
        row = db.query(WorkOrder).filter_by(production_order_id=po, production_batch_id=batch, operation="sewing").one()
        db.add(SewingRecord(work_order_id=row.id, production_batch_id=batch, input_qty=215, sewn_qty=215, passed_qty=215))
        row.passed_qty = row.actual_output_qty = 215
        db.flush()
        _complete_if_done(db, row)
        assert row.status == "completed"


def test_cutting_defects_are_not_counted_again_as_packaging_losses(client, auth_headers):
    from app.models.workflow_service import _complete_if_done
    po, batch, works, bundle, _ = routed_order()
    with TestSessionLocal() as db:
        db.get(Bundle, bundle).quantity = 90
        cut = db.query(CuttingRecord).filter_by(production_batch_id=batch).one()
        cut.cut_pieces, cut.passed_pieces, cut.defective_pieces = 100, 90, 10
        for op in ('sewing','packaging'):
            row = db.get(WorkOrder, works[op]); row.planned_input_qty = row.planned_output_qty = 100
        db.commit()
    result = client.patch(f'/api/work-orders/{works["cutting"]}/sewing-factory', headers=auth_headers,
        json={"sewing_factory_code":"BST","production_batch_ids":[batch]})
    assert result.status_code == 200, result.text
    with TestSessionLocal() as db:
        sewing = db.query(WorkOrder).filter_by(production_order_id=po,production_batch_id=batch,operation='sewing').one()
        packaging = db.query(WorkOrder).filter_by(production_order_id=po,production_batch_id=batch,operation='packaging').one()
        db.add(SewingRecord(work_order_id=sewing.id,production_batch_id=batch,input_qty=90,sewn_qty=85,passed_qty=85,failed_qty=5))
        sewing.passed_qty, sewing.failed_qty = 85,5
        packaging.passed_qty, packaging.status = 75,'in_progress'
        db.flush(); _complete_if_done(db,packaging)
        assert packaging.planned_output_qty == 90
        assert packaging.status == 'in_progress'
        assert all(db.get(WorkOrder,works[op]).status == 'completed' for op in ('sewing','packaging'))


def test_po0377_correction_preview_is_read_only_and_apply_preserves_history(client, auth_headers):
    import importlib.util
    from pathlib import Path
    from app.schemas import ProductionOrder
    spec = importlib.util.spec_from_file_location('correction', Path(__file__).resolve().parents[2]/'scripts/correct_po0377_nastil_factories.py')
    script = importlib.util.module_from_spec(spec); spec.loader.exec_module(script)
    po, first, _, _, ids = mixed_order()
    with TestSessionLocal() as db:
        db.get(ProductionOrder,po).production_no = 'PO-0377'
        db.commit()
        before = script.protected_fingerprints(db,po,ids)
        expected_identity = (po, first, *ids)
        preview = script.correct(db,expected_identity=expected_identity)
        assert not preview['applied']
        assert not db.new and not db.dirty and not db.deleted
        assert preview['protected_fingerprints'] == before
        applied = script.correct(db,actor_id=1,apply=True,expected_identity=expected_identity)
        assert applied['applied']
        assert script.protected_fingerprints(db,po,ids) == before
        db.commit()
    with TestSessionLocal() as db:
        assert {b.sewing_factory_code for b in db.query(Bundle).filter(Bundle.production_batch_id.in_(ids))} == {'BST'}
        assert {b.sewing_factory_code for b in db.query(Bundle).filter_by(production_batch_id=first)} == {'MIL'}

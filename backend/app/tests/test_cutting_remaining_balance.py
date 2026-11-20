from datetime import date

import pytest
from sqlalchemy import event, func

from app.models.department_dashboards_service import cutting_board
from app.models.production.cutting_balance_service import (
    balance_totals, cutting_balances, reconcile_cutting_evidence,
)
from app.schemas import Bundle, Department, Package, PackageBatchAllocation, PackagingRecord, ProductionBatch, SewingRecord, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_department_dashboards import DAY, bundle, order


def stage(db, po, operation):
    department = db.query(Department).filter_by(code="MIL" if operation == "sewing" else "PKG").one()
    work = WorkOrder(production_order_id=po.id, department_id=department.id,
                     operation=operation, status="in_progress")
    db.add(work)
    db.flush()
    return work


def test_board_excludes_fully_packed_and_retains_partial_without_acceptance(client, auth_headers):
    with TestSessionLocal() as db:
        po, _, record = order(db, "BALANCE-PARTIAL")
        first = bundle(db, po, record, "BALANCE-A", quantity=100)
        second = bundle(db, po, record, "BALANCE-B", quantity=100)
        sewing = stage(db, po, "sewing")
        packaging = stage(db, po, "packaging")
        db.add(SewingRecord(work_order_id=sewing.id, input_qty=150, sewn_qty=150, passed_qty=150))
        db.add(PackagingRecord(work_order_id=packaging.id, input_qty=150, packed_qty=150))
        db.commit()
        result = cutting_board(db, "CUT", DAY, DAY)
        assert result["totals"]["pieces"] == 50
        assert result["totals"]["bundles"] is None
        assert result["totals"]["unconfirmed_batches"] == 1
        assert cutting_board(db, "CUT", date(2025, 1, 1), date(2025, 1, 1))["totals"]["pieces"] == 50
        assert (first.quantity, first.status, second.quantity, second.status) == (100, "created", 100, "created")
        before = db.query(func.count(Bundle.id)).scalar()
        for _ in range(3):
            assert balance_totals(cutting_balances(db))["pieces"] == 50
        assert db.query(func.count(Bundle.id)).scalar() == before
    response = client.get("/api/bundles/cutting-inventory?page_size=1", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["total_quantity"] == 50
    assert response.json()["total_bundle_count"] is None
    assert response.json()["rows"][0]["cutting_balance"]["pieces"] == 50
    with TestSessionLocal() as db:
        db.add(PackagingRecord(work_order_id=packaging.id, input_qty=50, packed_qty=50))
        db.commit()
        assert cutting_board(db, "CUT", DAY, DAY)["totals"]["pieces"] == 0
    assert client.get("/api/bundles/cutting-inventory", headers=auth_headers).json()["rows"] == []


def source(identity, size="M", quantity=100, received=False, batch=1, factory="MIL", department="CUT"):
    return dict(kind="bundle", identity=identity, order_id=1, batch_id=batch,
                quantity=quantity, size=size, received=received, factory=factory,
                department=department, work_order_id=1)


def evidence(kind="sewing", quantity=0, inputs=0, outputs=0, losses=0, sizes=None, batch=1):
    return dict(kind=kind, identity=10, order_id=1, batch_id=batch, quantity=quantity,
                inputs=inputs, outputs=outputs, losses=losses, sizes=sizes)


def test_separate_input_output_and_stage_ledgers_are_overlapping_not_additive():
    groups = reconcile_cutting_evidence([source(1, quantity=200),
        evidence(inputs=80), evidence(quantity=80, outputs=75, losses=5),
        evidence("packaging", inputs=75, quantity=70, outputs=70, losses=5),
        evidence("package", quantity=70)])
    assert balance_totals(groups)["pieces"] == 120


def test_accepted_and_unlinked_same_size_output_has_honest_union_range():
    group, = reconcile_cutting_evidence([source(1, quantity=50, received=True),
                                        source(2, quantity=50), evidence(inputs=50, quantity=50)])
    assert group.pieces is None
    assert (group.pieces_min, group.pieces_max) == (0, 50)
    assert group.bundles is None


def test_complete_sizes_resolve_disjoint_accepted_output():
    group, = reconcile_cutting_evidence([source(1, size="L", received=True), source(2, size="M"),
        evidence(quantity=50, outputs=50, sizes=[{"size": "M", "quantity": 50}])])
    assert group.pieces == 50
    assert group.bundles == 1


def test_unknown_and_later_nastil_evidence_cannot_hide_other_batch():
    groups = reconcile_cutting_evidence([source(1, batch=1), source(2, batch=2),
        source(3, batch=None), evidence(inputs=100, batch=1), evidence(inputs=30, batch=None)])
    assert {g.batch_id: g.pieces for g in groups} == {2: 100, None: 70}


def test_partial_mixed_factories_or_cutting_origins_are_not_arbitrarily_debited():
    groups = reconcile_cutting_evidence([source(1), source(2, factory="ECO", department="ECT"), evidence(inputs=100)])
    assert len(groups) == 2
    assert all(g.pieces is None and (g.pieces_min, g.pieces_max) == (0, 100) for g in groups)


def test_full_consumption_resolves_even_mixed_factory_history():
    assert reconcile_cutting_evidence([source(1), source(2, factory="BST"), evidence(inputs=200)]) == []


def test_mixed_factory_bounds_preserve_exact_whole_batch_total():
    groups = reconcile_cutting_evidence([source(1), source(2, factory="BST"), evidence(inputs=100)])
    assert all(group.pieces is None for group in groups)
    assert balance_totals(groups)["pieces"] == 100


def test_known_size_overproduction_does_not_consume_other_size():
    group, = reconcile_cutting_evidence([source(1, size="M"), source(2, size="L"),
        evidence(quantity=150, outputs=150, sizes=[{"size": "M", "quantity": 150}])])
    assert group.pieces == 100


def test_unknown_later_ledger_may_overlap_known_size_overproduction():
    group, = reconcile_cutting_evidence([source(1, size="M"), source(2, size="L"),
        evidence(quantity=150, outputs=150, sizes=[{"size": "M", "quantity": 150}]),
        evidence("package", quantity=150)])
    assert group.pieces is None
    assert (group.pieces_min, group.pieces_max) == (50, 100)


def test_missing_status_counters_and_malformed_size_breakdown_do_not_invent_output():
    group, = reconcile_cutting_evidence([source(1), evidence(quantity=20, outputs=20,
        sizes=[{"size": "M", "quantity": 90}])])
    assert group.pieces == 80


def test_sql_projection_uses_one_select_and_current_correction_ledger():
    with TestSessionLocal() as db:
        po, _, record = order(db, "BALANCE-SNAPSHOT")
        bundle(db, po, record, "BALANCE-SNAPSHOT-B", quantity=100)
        work = stage(db, po, "sewing")
        output = SewingRecord(work_order_id=work.id, input_qty=40, sewn_qty=40, passed_qty=40)
        db.add(output)
        db.commit()
        selects = []
        def count_select(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                selects.append(statement)
        event.listen(db.bind, "before_cursor_execute", count_select)
        try:
            assert balance_totals(cutting_balances(db))["pieces"] == 60
        finally:
            event.remove(db.bind, "before_cursor_execute", count_select)
        assert len(selects) == 1
        output.input_qty = output.sewn_qty = output.passed_qty = 20
        db.commit()
        assert balance_totals(cutting_balances(db))["pieces"] == 80
        db.delete(output)
        db.commit()
        assert balance_totals(cutting_balances(db))["pieces"] == 100


@pytest.mark.parametrize("status", ["packed", "returned_to_packaging", "damaged", "shipped"])
def test_package_allocations_not_primary_batch_or_lifecycle_release_cutting(status):
    with TestSessionLocal() as db:
        po, _, record = order(db, "BALANCE-PACKAGES")
        first = ProductionBatch(production_order_id=po.id, batch_no="BALANCE-N1", batch_index=1)
        second = ProductionBatch(production_order_id=po.id, batch_no="BALANCE-N2", batch_index=2)
        db.add_all([first, second])
        db.flush()
        bundle(db, po, record, "BALANCE-PACK1", quantity=100).production_batch_id = first.id
        bundle(db, po, record, "BALANCE-PACK2", quantity=100).production_batch_id = second.id
        package = Package(package_no="BALANCE-PACK", barcode="BALANCE-PACK", production_order_id=po.id,
                          production_batch_id=first.id, model_id=po.model_id, color="blue",
                          total_quantity=90, quantity_shortfall=10, status=status)
        db.add(package)
        db.flush()
        db.add_all([PackageBatchAllocation(package_id=package.id, production_batch_id=first.id, quantity=60),
                    PackageBatchAllocation(package_id=package.id, production_batch_id=second.id, quantity=40)])
        db.commit()
        assert {g.batch_id: g.pieces for g in cutting_balances(db)} == {first.id: 40, second.id: 60}


def test_search_and_pagination_preserve_partial_batch_balance(client, auth_headers):
    with TestSessionLocal() as db:
        po, _, record = order(db, "BALANCE-SEARCH")
        bundle(db, po, record, "UNIQUE-FIRST", quantity=100)
        bundle(db, po, record, "OTHER-SECOND", quantity=100)
        work = stage(db, po, "sewing")
        db.add(SewingRecord(work_order_id=work.id, input_qty=150, sewn_qty=150, passed_qty=150))
        db.commit()
    for page in [1, 2]:
        response = client.get(f"/api/bundles/cutting-inventory?q=UNIQUE-FIRST&page_size=1&page={page}", headers=auth_headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total"] == 2 and result["total_quantity"] == 50
        assert result["total_bundle_count"] is None
        assert len(result["rows"]) == 1
        assert result["rows"][0]["quantity"] == 100
        assert result["rows"][0]["cutting_balance"]["pieces"] == 50

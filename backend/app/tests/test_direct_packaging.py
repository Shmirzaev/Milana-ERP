"""Direct labels consume actual passed Sewing exactly once in one transaction."""
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.schemas import (
    Department, FinishedGoodsStock, Item, ModelBOM, Package, PackagePrintRun,
    PackagingRecord, ProductionBatch, ProductionOrder, ProductionOrderItem,
    Role, SewingRecord, StockBatch, StockMovement, User, Warehouse, WasteRecord, WorkOrder,
)
from app.tests.conftest import TestSessionLocal
from app.tests.packaging_workflow_fixtures import seed_packaging_workflow

PATH = "/api/packages/print-runs/create-packages"


def seed(*, scenario="automatic", complete_sizes=True, factory="MIL"):
    with TestSessionLocal.begin() as db:
        facts = seed_packaging_workflow(db)[scenario]
        if complete_sizes:
            for row in db.query(SewingRecord).join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id).filter(
                    WorkOrder.production_order_id == facts["order_id"]):
                row.size_quantities = [{"size": "M", "quantity": row.passed_qty}]
        work = db.get(WorkOrder, facts["work_order_id"])
        work.department_id = db.query(Department.id).filter_by(code={"MIL": "PKG", "BST": "BPK", "ECO": "ECP"}[factory]).scalar()
    return facts


def headers(factory="MIL", user_id=1):
    return {"Authorization": "Bearer " + create_access_token(user_id, extra={"factory_code": factory})}


def package(facts, quantity=60, *, batch_id="default", **changes):
    if batch_id == "default":
        batch_id = facts["batch_ids"][0]
    return {"production_order_id": facts["order_id"], "production_batch_id": batch_id,
            "model_id": facts["model_id"], "color": "white", "capacity": 60,
            "weight_kg": 1.5, "items": [{"model_id": facts["model_id"], "color": "white", "size": "M", "quantity": quantity}],
            **changes}


def body(facts, packages=None, **changes):
    return {"request_key": str(uuid4()), "work_order_id": facts["work_order_id"],
            "packages": packages or [package(facts)], **changes}


def sources(client, facts, auth):
    response = client.get(f"/api/packages/sources/{facts['work_order_id']}", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def queue(client, facts, auth, department="PKG"):
    response = client.get("/api/packaging/received-orders", headers=auth,
                          params={"packaging_department_code": department})
    assert response.status_code == 200, response.text
    return [row for row in response.json() if row["production_order_id"] == facts["order_id"]]


def quantities(facts):
    with TestSessionLocal() as db:
        records = db.query(PackagingRecord).join(WorkOrder, WorkOrder.id == PackagingRecord.work_order_id).filter(
            WorkOrder.production_order_id == facts["order_id"]).all()
        packages = db.query(Package).filter_by(production_order_id=facts["order_id"]).all()
        return (len(records), sum(row.input_qty for row in records), sum(row.packed_qty for row in records),
                sum(row.damaged_qty for row in records), len(packages), sum(row.total_quantity for row in packages))


@pytest.mark.parametrize("factory,department", [("MIL", "PKG"), ("BST", "BPK"), ("ECO", "ECP")])
def test_direct_partial_retry_and_remaining_without_any_manual_record(client, auth_headers, factory, department):
    facts = seed(factory=factory)
    auth = headers(factory)
    assert sources(client, facts, auth)["items"][0]["available_to_package"] == 95
    assert quantities(facts) == (0, 0, 0, 0, 0, 0)
    request = body(facts)
    result = client.post(PATH, headers=auth, json=request)
    assert result.status_code == 201, result.text
    assert client.post(PATH, headers=auth, json=request).json() == result.json()
    assert quantities(facts) == (1, 60, 60, 0, 1, 60)
    assert sources(client, facts, auth)["items"][0]["available_to_package"] == 35
    assert queue(client, facts, auth, department)[0]["remaining_quantity"] == 35
    with TestSessionLocal() as db:
        work = db.get(WorkOrder, facts["work_order_id"])
        assert (work.actual_input_qty, work.actual_output_qty, work.passed_qty) == (60, 60, 60)
        assert work.status == "in_progress" and work.start_time is not None and work.end_time is None
        assert db.query(Package).filter_by(production_order_id=facts["order_id"]).one().received_at is None
        # Inventory availability queries require physical warehouse receipt,
        # even though the pre-receipt accounting row exists for the package.
        eligible = db.query(FinishedGoodsStock).join(Package, Package.id == FinishedGoodsStock.package_id).filter(
            Package.production_order_id == facts["order_id"], Package.received_at.is_not(None)).count()
        assert eligible == 0
    last = client.post(PATH, headers=auth, json=body(facts, [package(facts, 35)]))
    assert last.status_code == 201, last.text
    assert quantities(facts) == (2, 95, 95, 0, 2, 95)
    with TestSessionLocal() as db:
        work = db.get(WorkOrder, facts["work_order_id"])
        assert work.status == "completed" and work.start_time is not None and work.end_time is not None
    assert queue(client, facts, auth, department) == []


def test_saved_unlabelled_and_unrecorded_selected_sources_do_not_double_consume(client, auth_headers):
    facts = seed(scenario="legacy_later")
    first, second, untouched = facts["batch_ids"]
    initial = sources(client, facts, auth_headers)["items"]
    assert [row["available_to_package"] for row in initial] == [80, 70, 90]
    mixed = package(facts, 60, batch_id=None, batch_allocations=[
        {"production_batch_id": first, "quantity": 35, "item_breakdown": [{"model_id": facts["model_id"], "color": "white", "size": "M", "quantity": 35}]},
        {"production_batch_id": second, "quantity": 25, "item_breakdown": [{"model_id": facts["model_id"], "color": "white", "size": "M", "quantity": 25}]}])
    result = client.post(PATH, headers=auth_headers, json=body(facts, [mixed]))
    assert result.status_code == 201, result.text
    assert quantities(facts) == (2, 75, 75, 0, 1, 60)
    assert [row["available_to_package"] for row in sources(client, facts, auth_headers)["items"]] == [45, 45, 90]
    # Exhaust first's new45 while keeping second's saved15 and third untouched.
    result = client.post(PATH, headers=auth_headers, json=body(facts, [package(facts, 45)]))
    assert result.status_code == 201, result.text
    assert quantities(facts) == (3, 120, 120, 0, 2, 105)
    assert [row["available_to_package"] for row in sources(client, facts, auth_headers)["items"]] == [0, 45, 90]
    assert queue(client, facts, auth_headers)[0]["remaining_quantity"] == 135
    with TestSessionLocal() as db:
        assert not db.query(PackagingRecord).filter_by(production_batch_id=untouched).count()


def test_full_saved_output_remains_in_queue_until_all_labels_are_created(client, auth_headers):
    facts = seed()
    with TestSessionLocal.begin() as db:
        work = db.get(WorkOrder, facts["work_order_id"])
        db.add(PackagingRecord(work_order_id=work.id, production_batch_id=facts["batch_ids"][0], input_qty=95, packed_qty=95))
        work.actual_input_qty = work.actual_output_qty = work.passed_qty = 95
    assert queue(client, facts, auth_headers)[0]["remaining_quantity"] == 95
    result = client.post(PATH, headers=auth_headers, json=body(facts))
    assert result.status_code == 201, result.text
    assert quantities(facts) == (1, 95, 95, 0, 1, 60)
    assert queue(client, facts, auth_headers)[0]["remaining_quantity"] == 35


def add_material(facts, amount):
    with TestSessionLocal.begin() as db:
        item = Item(sku="DIRECT-BAG", name="Direct bag", category="packaging", unit="pcs")
        db.add(item); db.flush()
        batch = StockBatch(batch_no="DIRECT-BAG-01", item_id=item.id, quantity=amount, unit="pcs",
                           warehouse_id=db.query(Warehouse.id).first()[0])
        db.add(batch); db.flush()
        db.add(ModelBOM(model_id=facts["model_id"], item_id=item.id, quantity_per_piece=1, unit="pcs"))
        return batch.id


def test_damage_material_and_waste_are_atomic_and_retry_does_not_repeat_them(client, auth_headers):
    facts = seed()
    material = add_material(facts, 200)
    request = body(facts, damaged_qty=5)
    response = client.post(PATH, headers=auth_headers, json=request)
    assert response.status_code == 201, response.text
    assert client.post(PATH, headers=auth_headers, json=request).json() == response.json()
    assert quantities(facts) == (1, 65, 60, 5, 1, 60)
    with TestSessionLocal() as db:
        assert db.get(StockBatch, material).quantity == 140
        assert db.query(StockMovement).filter_by(batch_id=material, reference_type="PackagingRecord").count() == 1
        waste = db.query(WasteRecord).filter_by(production_order_id=facts["order_id"]).one()
        assert waste.quantity == 5 and waste.waste_type == "packaging_damage"
        assert db.get(WorkOrder, facts["work_order_id"]).failed_qty == 5
    assert queue(client, facts, auth_headers)[0]["remaining_quantity"] == 30


@pytest.mark.parametrize("failure", ["material", "second_package"])
def test_failed_combined_action_rolls_back_evidence_materials_packages_and_counters(client, auth_headers, failure):
    facts = seed()
    material = add_material(facts, 50 if failure == "material" else 200)
    if failure == "material":
        with TestSessionLocal.begin() as db:
            db.get(StockBatch, material).unit = "kg"
    request = body(facts) if failure == "material" else body(facts, [package(facts, 30), package(facts, 65)])
    response = client.post(PATH, headers=auth_headers, json=request)
    assert response.status_code == (409 if failure == "material" else 400), response.text
    assert quantities(facts) == (0, 0, 0, 0, 0, 0)
    with TestSessionLocal() as db:
        assert db.get(StockBatch, material).quantity == (50 if failure == "material" else 200)
        assert db.query(StockMovement).filter_by(batch_id=material).count() == 0
        work = db.get(WorkOrder, facts["work_order_id"])
        assert (work.actual_input_qty, work.actual_output_qty, work.passed_qty, work.failed_qty) == (0, 0, 0, 0)
        assert db.query(PackagePrintRun).count() == 0
    # The failed key was not consumed. Correct and retry it without duplicate work.
    if failure == "second_package":
        request["packages"] = [package(facts, 60), package(facts, 35)]
        fixed = client.post(PATH, headers=auth_headers, json=request)
        assert fixed.status_code == 201, fixed.text
        assert quantities(facts) == (1, 95, 95, 0, 2, 95)


@pytest.mark.parametrize("invalid", ["color", "size", "actual_size", "overbudget", "wrong_anchor", "wrong_batch", "usluga"])
def test_direct_refusals_create_no_records_or_packages(client, auth_headers, invalid):
    facts = seed()
    request = body(facts)
    if invalid in {"color", "size"}:
        request["packages"][0]["items"][0][invalid] = "invented"
    elif invalid == "actual_size":
        with TestSessionLocal.begin() as db:
            row = db.query(SewingRecord).filter_by(work_order_id=facts["sewing_work_order_id"]).one()
            row.size_quantities = [{"size": "M", "quantity": 35}, {"size": "L", "quantity": 60}]
            db.add(ProductionOrderItem(production_order_id=facts["order_id"], model_id=facts["model_id"], color="white", size="L", planned_quantity=60))
    elif invalid == "overbudget":
        request["packages"] = [package(facts, 60), package(facts, 36)]
    elif invalid == "wrong_anchor":
        request["work_order_id"] = facts["sewing_work_order_id"]
    elif invalid == "wrong_batch":
        request["packages"][0]["production_batch_id"] = 2_147_483_647
    else:
        with TestSessionLocal.begin() as db:
            db.get(ProductionOrder, facts["order_id"]).source_type = "usluga"
    response = client.post(PATH, headers=auth_headers, json=request)
    assert response.status_code in {400, 404, 409}, response.text
    assert quantities(facts) == (0, 0, 0, 0, 0, 0)


def test_incomplete_actual_sizes_keeps_operator_recipe_without_inventing_actual_distribution(client, auth_headers):
    facts = seed(complete_sizes=False)
    response = client.post(PATH, headers=auth_headers, json=body(facts))
    assert response.status_code == 201, response.text
    with TestSessionLocal() as db:
        assert db.query(SewingRecord).filter_by(work_order_id=facts["sewing_work_order_id"]).one().size_quantities == []


def test_legacy_unbatched_source_and_explicit_compatibility_mode(client, auth_headers):
    facts = seed()
    with TestSessionLocal.begin() as db:
        db.query(SewingRecord).filter_by(work_order_id=facts["sewing_work_order_id"]).update({SewingRecord.production_batch_id: None})
        db.query(ProductionBatch).filter_by(production_order_id=facts["order_id"]).delete()
    row = package(facts, batch_id=None)
    # Old clients remain saved-output-only: no silent fallback from a failed old request.
    legacy = client.post(PATH, headers=auth_headers, json={"request_key": str(uuid4()), "packages": [row]})
    assert legacy.status_code == 409
    state = sources(client, facts, auth_headers)
    assert state["items"] == [] and state["unbatched_source"]["available_to_package"] == 95
    direct = client.post(PATH, headers=auth_headers, json=body(facts, [row]))
    assert direct.status_code == 201, direct.text
    assert sources(client, facts, auth_headers)["unbatched_source"]["available_to_package"] == 35


def test_package_only_role_reads_queue_context_and_creates_but_cannot_cross_factory(client, auth_headers):
    facts = seed()
    with TestSessionLocal.begin() as db:
        role = Role(name="Direct packages only", permissions=["packaging.packages"])
        db.add(role); db.flush()
        actor = User(name="Direct packages", email="direct-only@example.invalid", password_hash="unused", role_id=role.id,
                     factory_code="MIL", department_id=db.query(Department.id).filter_by(code="PKG").scalar())
        db.add(actor); db.flush(); actor_id = actor.id
    auth = headers(user_id=actor_id)
    assert queue(client, facts, auth)[0]["remaining_quantity"] == 95
    assert client.get(f"/api/work-orders/{facts['work_order_id']}", headers=auth).status_code == 200
    assert client.get(f"/api/production-orders/{facts['order_id']}", headers=auth).status_code == 200
    assert client.get(f"/api/work-orders/{facts['work_order_id']}/packaging-batch-progress", headers=auth).status_code == 200
    assert sources(client, facts, auth)["items"][0]["available_to_package"] == 95
    response = client.post(PATH, headers=auth, json=body(facts))
    assert response.status_code == 201, response.text
    with TestSessionLocal.begin() as db:
        db.get(WorkOrder, facts["work_order_id"]).department_id = db.query(Department.id).filter_by(code="ECP").scalar()
    denied = client.post(PATH, headers=auth, json=body(facts, [package(facts, 35)]))
    assert denied.status_code == 403, denied.text
    assert quantities(facts) == (1, 60, 60, 0, 1, 60)


@pytest.mark.parametrize("grade,quantity", [("first_grade", 1), ("second_grade", 30)])
def test_direct_graded_output_keeps_size_stock_and_receipt_guards(client, auth_headers, grade, quantity):
    facts = seed()
    row = package(facts, quantity, stock_kind=grade, capacity=quantity)
    response = client.post(PATH, headers=auth_headers, json=body(facts, [row]))
    assert response.status_code == 201, response.text
    assert quantities(facts) == (1, quantity, quantity, 0, 1, quantity)
    assert client.get("/api/sales-orders/first-grade-options", headers=auth_headers).json() == []
    if grade == "first_grade":
        ordinary = client.post(PATH, headers=auth_headers, json=body(facts, [package(facts, 60)]))
        assert ordinary.status_code == 201, ordinary.text
        assert quantities(facts) == (2, 61, 61, 0, 2, 61)


def test_graded_missing_size_evidence_is_still_refused_without_automatic_inference(client, auth_headers):
    facts = seed(complete_sizes=False)
    response = client.post(PATH, headers=auth_headers,
                           json=body(facts, [package(facts, 1, stock_kind="first_grade", capacity=1)]))
    assert response.status_code == 409, response.text
    assert quantities(facts) == (0, 0, 0, 0, 0, 0)


def test_damage_only_action_retries_reconciles_and_never_creates_labels_or_stock(client, auth_headers):
    facts = seed()
    request = {"request_key": str(uuid4()), "work_order_id": facts["work_order_id"],
               "production_batch_id": facts["batch_ids"][0], "damaged_qty": 95}
    path = "/api/packages/record-damage"
    response = client.post(path, headers=auth_headers, json=request)
    assert response.status_code == 201, response.text
    assert response.json()["damaged_qty"] == 95
    assert client.post(path, headers=auth_headers, json=request).json() == response.json()
    recovered = client.post(path + "/reconcile", headers=auth_headers, json=request)
    assert recovered.json() == {"status": "completed", "result": response.json()}
    assert quantities(facts) == (1, 95, 0, 95, 0, 0)
    assert queue(client, facts, auth_headers) == []
    with TestSessionLocal() as db:
        assert db.query(WasteRecord).filter_by(production_order_id=facts["order_id"]).one().quantity == 95
        assert db.query(FinishedGoodsStock).filter_by(production_order_id=facts["order_id"]).count() == 0
        assert db.query(PackagePrintRun).count() == 0
    assert client.post(path, headers=auth_headers, json={**request, "damaged_qty": 1}).status_code == 409
    assert client.post(path, headers=auth_headers, json={**request, "request_key": str(uuid4()), "damaged_qty": 1}).status_code == 400


def test_damage_reconciliation_cancels_uncommitted_request_and_factory_denial_is_atomic(client, auth_headers):
    facts = seed()
    request = {"request_key": str(uuid4()), "work_order_id": facts["work_order_id"],
               "production_batch_id": facts["batch_ids"][0], "damaged_qty": 10}
    path = "/api/packages/record-damage"
    cancelled = client.post(path + "/reconcile", headers=auth_headers, json=request)
    assert cancelled.json() == {"status": "cancelled"}
    assert client.post(path, headers=auth_headers, json=request).status_code == 409
    assert client.post(path, headers=headers("ECO"), json={**request, "request_key": str(uuid4())}).status_code == 403
    assert quantities(facts) == (0, 0, 0, 0, 0, 0)


def test_usluga_confirmed_output_leaves_queue_without_warehouse_side_effects(client, auth_headers):
    facts = seed()
    with TestSessionLocal.begin() as db:
        order = db.get(ProductionOrder, facts["order_id"])
        order.source_type = "usluga"
        work = db.get(WorkOrder, facts["work_order_id"])
        work.service_packaging_json = {"done": True, "confirmed_quantity": 95, "items": [{"size": "M", "quantity": 95}]}
        work.status = "completed"
        work.actual_input_qty = work.actual_output_qty = work.passed_qty = 95
    assert queue(client, facts, auth_headers) == []
    assert quantities(facts) == (0, 0, 0, 0, 0, 0)


def test_re_routed_source_uses_all_historical_record_input_and_reconstructs_counter(client, auth_headers):
    facts = seed()
    with TestSessionLocal.begin() as db:
        shared = db.get(WorkOrder, facts["work_order_id"])
        db.add(PackagingRecord(work_order_id=shared.id, production_batch_id=facts["batch_ids"][0],
                               input_qty=40, packed_qty=30, damaged_qty=10))
        exact = WorkOrder(production_order_id=facts["order_id"], production_batch_id=facts["batch_ids"][0],
                          operation="packaging", department_id=shared.department_id, status="ready",
                          planned_input_qty=95, planned_output_qty=95, actual_input_qty=999,
                          actual_output_qty=888, passed_qty=777, failed_qty=666)
        db.add(exact); db.flush(); exact_id = exact.id
    # 30 saved +55 unrecorded95−40, never the original95 again.
    state = sources(client, facts, auth_headers)["items"][0]
    assert state["available_to_package"] == 85 and state["available_input_qty"] == 55
    result = client.post(PATH, headers=auth_headers, json=body(facts, [package(facts, 60)]))
    assert result.status_code == 201, result.text
    assert quantities(facts) == (2, 70, 60, 10, 1, 60)
    with TestSessionLocal() as db:
        work = db.get(WorkOrder, exact_id)
        assert (work.actual_input_qty, work.actual_output_qty, work.passed_qty, work.failed_qty) == (30, 30, 30, 0)


def test_cancelled_foreign_exact_owner_does_not_hide_active_shared_source(client, auth_headers):
    facts = seed()
    with TestSessionLocal.begin() as db:
        cancelled = WorkOrder(production_order_id=facts["order_id"], production_batch_id=facts["batch_ids"][0],
                              operation="packaging", status="cancelled",
                              department_id=db.query(Department.id).filter_by(code="ECP").scalar())
        db.add(cancelled)
    assert queue(client, facts, auth_headers)[0]["remaining_quantity"] == 95
    assert sources(client, facts, auth_headers)["items"][0]["available_to_package"] == 95
    result = client.post(PATH, headers=auth_headers, json=body(facts))
    assert result.status_code == 201, result.text
    with TestSessionLocal() as db:
        assert db.query(Package).filter_by(production_order_id=facts["order_id"]).one().packaging_department_code == "PKG"


def test_damage_on_multiple_sources_is_explicitly_refused(client, auth_headers):
    facts = seed(scenario="legacy_later")
    first, second, _ = facts["batch_ids"]
    mixed = package(facts, 60, batch_id=None, batch_allocations=[
        {"production_batch_id": first, "quantity": 35}, {"production_batch_id": second, "quantity": 25}])
    result = client.post(PATH, headers=auth_headers, json=body(facts, [mixed], damaged_qty=1))
    assert result.status_code == 400, result.text
    assert quantities(facts) == (2, 75, 75, 0, 0, 0)


@pytest.mark.parametrize("customer_order", [False, True])
def test_direct_source_customer_cannot_be_relinked_and_default_uses_real_owner(client, auth_headers, customer_order):
    from app.schemas import Customer, SalesOrder
    facts = seed()
    with TestSessionLocal.begin() as db:
        customer_id = db.query(Customer.id).first()[0]
        owner = SalesOrder(order_no=f"SO-OWNER-{uuid4().hex[:8]}", customer_id=customer_id)
        other = SalesOrder(order_no=f"SO-OTHER-{uuid4().hex[:8]}", customer_id=customer_id)
        db.add_all([owner, other]); db.flush()
        owner_id, other_id = owner.id, other.id
        if customer_order:
            db.get(ProductionOrder, facts["order_id"]).sales_order_id = owner_id
    invalid = client.post(PATH, headers=auth_headers,
                          json=body(facts, [package(facts, sales_order_id=other_id)]))
    assert invalid.status_code == 409, invalid.text
    assert quantities(facts) == (0, 0, 0, 0, 0, 0)
    with TestSessionLocal() as db:
        assert db.get(ProductionOrder, facts["order_id"]).sales_order_id == (owner_id if customer_order else None)
    valid = client.post(PATH, headers=auth_headers, json=body(facts))
    assert valid.status_code == 201, valid.text
    with TestSessionLocal() as db:
        assert db.query(Package).filter_by(production_order_id=facts["order_id"]).one().sales_order_id == (owner_id if customer_order else None)


@pytest.mark.parametrize("direct", [False, True])
def test_partial_damage_starts_only_the_direct_workflow(client, auth_headers, direct):
    facts = seed()
    if direct:
        response = client.post("/api/packages/record-damage", headers=auth_headers, json={
            "request_key": str(uuid4()), "work_order_id": facts["work_order_id"],
            "production_batch_id": facts["batch_ids"][0], "damaged_qty": 10})
    else:
        response = client.post("/api/packaging/records", headers=auth_headers, json={
            "work_order_id": facts["work_order_id"], "production_batch_id": facts["batch_ids"][0],
            "input_qty": 10, "packed_qty": 0, "damaged_qty": 10})
    assert response.status_code in {200, 201}, response.text
    with TestSessionLocal() as db:
        work = db.get(WorkOrder, facts["work_order_id"])
        assert work.status == ("in_progress" if direct else "ready")
        assert (work.start_time is not None) == direct
        assert work.end_time is None
    assert quantities(facts) == (1, 10, 0, 10, 0, 0)

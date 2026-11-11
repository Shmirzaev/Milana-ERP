"""End-to-end pricing handoff and conservation of the manufacturing ledger."""
from decimal import Decimal
from datetime import datetime, timezone
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.db.session import SessionLocal
from app.schemas import AuditLog, CuttingPassport, Model, Notification, PriceCalculationRequest, User
from app.tests.test_price_calculation_workflow import _login, _setup_workflow_data
from app.tests.test_passport_cutting_submission import passport_cutting  # noqa: F401


PROTECTED_TABLES = (
    "sales_orders", "sales_order_items", "production_orders", "production_order_items", "work_orders",
    "production_batches", "stock_batches", "stock_movements", "material_reservations", "bundles",
    "printing_records", "sewing_records", "packaging_records", "packages", "finished_goods_stock", "shipments",
)


def protected_facts(db):
    from app.db.base import Base
    return {name: [tuple(row) for row in db.execute(select(Base.metadata.tables[name]).order_by(Base.metadata.tables[name].c.id))]
            for name in PROTECTED_TABLES if name in Base.metadata.tables}


def setup(client, suffix, *, complete=True):
    data = _setup_workflow_data(suffix)
    with SessionLocal() as db:
        model = db.get(Model, data["model_id"])
        code = model.code
        # The optional malformed PLM margin must not prevent valid Cutting work.
        model.details_json = {**model.details_json, "costing": {"target_margin_pct": "Infinity"}}
        db.commit()
    payload = {"passport_no": f"AUTO-{suffix}", "date": "2026-11-10T00:00:00Z", "model_code": code,
               "size_range": "S, M"}
    if complete:
        payload.update(fabric_width_m=2, lay_length_m=4, gramage=0.2, beka_per_piece_kg=0.01)
    headers = _login(client, f"cutting.price.{suffix}@example.com")
    saved = client.post("/api/cutting-passports", headers=headers, json=payload)
    assert saved.status_code == 201, saved.text
    data.update(passport=saved.json(), payload=payload,
        cutting=headers, purchasing=_login(client, f"abbosbek.price.{suffix}@example.com"),
        accessories=_login(client, f"accessory.price.{suffix}@example.com"), finance=_login(client, f"finance.price.{suffix}@example.com"))
    with SessionLocal() as db:
        request = db.query(PriceCalculationRequest).filter_by(active_model_id=data["model_id"]).one()
        data["request_id"] = request.id
    return data


def get_request(client, data, headers=None):
    response = client.get("/api/price-calculation/requests", headers=headers or data["finance"])
    assert response.status_code == 200, response.text
    return next(row for row in response.json() if row["id"] == data["request_id"])


def save_costs(client, data, *, no_accessories=False):
    request = get_request(client, data)
    base = f"/api/price-calculation/requests/{data['request_id']}"
    purchasing = client.patch(base + "/purchasing", headers=data["purchasing"], json={
        "expected_revision": request["revision"], "materials": [{"key": row["key"], "rate": 5} for row in request["materials"]],
        "sewing_cost": 0.5, "printing_cost": 0.2 if request["printing_required"] else None})
    assert purchasing.status_code == 200, purchasing.text
    accessories = client.patch(base + "/accessories", headers=data["accessories"], json={
        "expected_revision": purchasing.json()["revision"],
        "accessories": [] if no_accessories else [{"name": "Label", "price": 0.05}],
        "no_accessories_reason": "No trims needed" if no_accessories else None})
    assert accessories.status_code == 200, accessories.text
    return accessories.json()


def submit(client, data, team, request=None):
    request = request or get_request(client, data)
    response = client.post(f"/api/price-calculation/requests/{data['request_id']}/submit/{team}", headers=data[team],
        json={"expected_revision": request["revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_auto_request_keeps_incomplete_passport_saveable_and_reuses_slot(client):
    data = setup(client, "incomplete", complete=False)
    request = get_request(client, data)
    assert request["workflow_state"] == "collecting"
    assert request["cost_price"] is None
    assert "passport_consumption" in request["calculation_issues"]
    assert request["cutting_passport_id"] == data["passport"]["id"]
    for index in range(3):
        response = client.post("/api/cutting-passports", headers=data["cutting"], json=data["payload"] | {"passport_no": f"LATER-{index}"})
        assert response.status_code == 201, response.text
    with SessionLocal() as db:
        assert db.query(PriceCalculationRequest).filter_by(model_id=data["model_id"]).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", action="create", entity_id=request["id"]).count() == 1


def test_full_handoff_draft_submit_approve_and_order_conservation(client, auth_headers):
    data = setup(client, "handoff")
    # Existing agreed Sales line/total must remain independent of the variant price.
    order = client.post("/api/sales-orders", headers=auth_headers, json={"items": [{"model_id": data["model_id"], "color": "gray", "size": "S", "quantity": 4, "unit_price": 1.25}]})
    assert order.status_code == 201, order.text
    with SessionLocal() as db:
        before = protected_facts(db)
    request = save_costs(client, data)
    assert request["purchasing_status"] == request["accessories_status"] == "in_progress"
    assert request["cost_price"] is None
    request = submit(client, data, "purchasing", request)
    pending = client.get("/api/price-calculation/requests?queue=pending&team=purchasing", headers=data["purchasing"])
    assert all(row["id"] != request["id"] for row in pending.json())
    pending_accessories = client.get("/api/price-calculation/requests?queue=pending&team=accessories", headers=data["accessories"])
    assert any(row["id"] == request["id"] for row in pending_accessories.json())
    request = submit(client, data, "accessories", request)
    assert request["workflow_state"] == "awaiting_finance"
    assert request["cost_price"] == pytest.approx(4.7)  # 0.8 kg * 5 + 0.01 binding * 5 + .5 + .1 + .05
    base = f"/api/price-calculation/requests/{request['id']}"
    draft = client.patch(base + "/finance", headers=data["finance"], json={"selling_price": 6, "exchange_rate": 12500, "expected_revision": request["revision"]})
    assert draft.status_code == 200, draft.text
    assert draft.json()["cost_price_uzs"] == 58750
    with SessionLocal() as db:
        assert db.get(Model, data["model_id"]).selling_price is None
        assert protected_facts(db) == before
        finance_id = db.query(User.id).filter_by(email="finance.price.handoff@example.com").scalar()
        assert db.query(Notification).filter_by(title="Price ready for Finance approval", user_id=finance_id).count() == 1
    # finance.view grants viewing/drafts, never approval.
    assert client.post(base + "/approve", headers=data["finance"], json={"expected_revision": draft.json()["revision"], "selling_price": 6}).status_code == 403
    approved = client.post(base + "/approve", headers=auth_headers, json={"expected_revision": draft.json()["revision"], "selling_price": 6})
    assert approved.status_code == 200, approved.text
    assert approved.json()["workflow_state"] == "approved"
    assert approved.json()["selling_price_attached"]
    with SessionLocal() as db:
        assert protected_facts(db) == before
        assert db.get(Model, data["model_id"]).selling_price == Decimal("6.0000")
        stored = db.get(PriceCalculationRequest, request["id"])
        assert stored.active_model_id is None
        assert stored.approval_snapshot_json["cost_price"] == pytest.approx(4.7)
    assert client.patch(base + "/finance", headers=data["finance"], json={"selling_price": 9}).status_code == 409
    repeated = client.post("/api/cutting-passports", headers=data["cutting"], json=data["payload"] | {"passport_no": "PRICED-REUSE"})
    assert repeated.status_code == 201
    with SessionLocal() as db:
        assert db.query(PriceCalculationRequest).filter_by(model_id=data["model_id"]).count() == 1
        assert db.get(Model, data["model_id"]).selling_price == 6


def test_correction_reopens_only_the_affected_team_and_stale_write_refused(client, auth_headers):
    data = setup(client, "correction")
    request = save_costs(client, data, no_accessories=True)
    request = submit(client, data, "purchasing", request)
    request = submit(client, data, "accessories", request)
    base = f"/api/price-calculation/requests/{request['id']}"
    response = client.post(base + "/return", headers=auth_headers, json={"expected_revision": request["revision"], "team": "purchasing", "reason": "Check sewing cost"})
    assert response.status_code == 200, response.text
    returned = response.json()
    assert returned["purchasing_submitted_at"] is None and returned["accessories_submitted_at"]
    assert returned["workflow_state"] == "collecting"
    assert client.patch(base + "/purchasing", headers=data["purchasing"], json={"expected_revision": request["revision"], "sewing_cost": 1}).status_code == 409
    updated = client.patch(base + "/purchasing", headers=data["purchasing"], json={"expected_revision": returned["revision"], "sewing_cost": 1})
    assert updated.status_code == 200, updated.text
    submitted = submit(client, data, "purchasing", updated.json())
    assert submitted["workflow_state"] == "awaiting_finance"
    assert submitted["correction_reason"] is None


def test_passport_change_invalidates_submissions_not_orders(client):
    data = setup(client, "source-change")
    request = submit(client, data, "accessories", submit(client, data, "purchasing", save_costs(client, data)))
    with SessionLocal() as db:
        before = protected_facts(db)
    updated = client.patch(f"/api/cutting-passports/{data['passport']['id']}", headers=data["cutting"], json=data["payload"] | {"lay_length_m": 5})
    assert updated.status_code == 200, updated.text
    changed = get_request(client, data)
    assert changed["revision"] > request["revision"]
    assert changed["purchasing_submitted_at"] is None and changed["accessories_submitted_at"] is None
    assert changed["materials"][0]["consumption"] == 1
    with SessionLocal() as db:
        assert protected_facts(db) == before


def test_saved_price_wins_over_pending_approval(client, auth_headers):
    data = setup(client, "import-race")
    request = submit(client, data, "accessories", submit(client, data, "purchasing", save_costs(client, data)))
    with SessionLocal() as db:
        model = db.get(Model, data["model_id"])
        model.selling_price = 7
        model.selling_price_currency = "USD"
        model.selling_price_source = "import"
        db.commit()
    response = client.post(f"/api/price-calculation/requests/{request['id']}/approve", headers=auth_headers, json={"expected_revision": request["revision"], "selling_price": 6})
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.get(Model, data["model_id"]).selling_price == 7
        assert db.get(PriceCalculationRequest, request["id"]).approved_at is None


def test_report_excel_current_history_and_permissions(client, auth_headers):
    data = setup(client, "report")
    request = submit(client, data, "accessories", submit(client, data, "purchasing", save_costs(client, data)))
    response = client.post(f"/api/price-calculation/requests/{request['id']}/approve", headers=auth_headers, json={"expected_revision": request["revision"], "selling_price": 6})
    assert response.status_code == 200, response.text
    for suffix in ("report", "report.xlsx", f"models/{data['model_id']}/history"):
        assert client.get("/api/price-calculation/" + suffix, headers=data["purchasing"]).status_code == 403
    report = client.get("/api/price-calculation/report?q=PC-TEST-report&status=priced", headers=data["finance"])
    assert report.status_code == 200, report.text
    assert len(report.json()) == 1 and report.json()[0]["selling_price"] == 6
    excel = client.get("/api/price-calculation/report.xlsx?q=PC-TEST-report&status=priced", headers=data["finance"])
    assert excel.status_code == 200, excel.text
    book = load_workbook(BytesIO(excel.content), data_only=True)
    assert book.sheetnames == ["Variant Prices", "Cost Breakdown", "Approval History"]
    assert book["Variant Prices"].max_row == 2
    assert book["Variant Prices"]["E2"].value == 6
    assert book["Cost Breakdown"]["I2"].value == 4
    assert book["Approval History"]["F2"].value == 6


def test_metre_multi_material_grouped_consumption_and_zero_costs(client, auth_headers):
    data = setup(client, "mixed")
    with SessionLocal() as db:
        passport = db.get(CuttingPassport, data["passport"]["id"])
        passport.materials = [
            {"stock_batch_id": 101, "batch_allocations": [{"stock_batch_id": 101, "quantity": 3}, {"stock_batch_id": 102, "quantity": 3}], "fabric_type": "Cotton", "size_range": "S, M", "fabric_width_m": 2, "lay_length_m": 4, "gramage": .2},
            {"stock_batch_id": 103, "fabric_type": "Lining", "size_range": "S, M", "meter_mode": True, "lay_length_m": 2, "beka_per_piece_kg": .02}]
        from app.models.planning.variant_pricing_service import sync_passport_pricing
        sync_passport_pricing(db, passport, db.get(User, 1))
        db.commit()
    request = get_request(client, data)
    assert [(row["unit"], row["consumption"]) for row in request["materials"]] == [("kg", .8), ("m", 1), ("m", .02)]
    base = f"/api/price-calculation/requests/{request['id']}"
    saved = client.patch(base + "/purchasing", headers=data["purchasing"], json={"materials": [{"key": row["key"], "rate": 0} for row in request["materials"]], "sewing_cost": 0})
    assert saved.status_code == 200, saved.text
    no_accessories = client.patch(base + "/accessories", headers=data["accessories"], json={"accessories": [], "no_accessories_reason": "No accessories needed"})
    assert no_accessories.status_code == 200
    ready = submit(client, data, "accessories", submit(client, data, "purchasing"))
    assert ready["cost_price"] == .1


def test_factory_and_catalogue_scope_applies_to_queue_mutation_and_excel(client, auth_headers):
    data = setup(client, "scope")
    with SessionLocal() as db:
        actor = db.query(User).filter(User.email == "finance.price.scope@example.com").one()
        actor.factory_code = "ECO"
        db.commit()
    eco_finance = _login(client, "finance.price.scope@example.com")
    response = client.get("/api/price-calculation/requests", headers=eco_finance)
    assert response.status_code == 200 and all(row["id"] != data["request_id"] for row in response.json())
    assert client.patch(f"/api/price-calculation/requests/{data['request_id']}/finance", headers=eco_finance, json={"selling_price": 9}).status_code == 403
    for route in ("requests", "report", "report.xlsx"):
        assert client.get(f"/api/price-calculation/{route}?catalog_scope=usluga", headers=auth_headers).status_code == 403


def test_pricing_hook_does_not_modify_any_order_or_stock_fact(client, auth_headers, passport_cutting, monkeypatch):
    from app.models.planning import variant_pricing_service
    batches, order, work, payload = passport_cutting
    original = variant_pricing_service.sync_passport_pricing
    checked = []
    def prove_isolation(db, passport, current):
        before = protected_facts(db)
        original(db, passport, current)
        assert protected_facts(db) == before
        checked.append(True)
    monkeypatch.setattr(variant_pricing_service, "sync_passport_pricing", prove_isolation)
    saved = client.post("/api/cutting-passports", headers=auth_headers, json={"production_order_id": order["id"], "date": "2026-11-10T00:00:00Z", "pieces": 10})
    assert saved.status_code == 201, saved.text
    assert checked == [True]
    # Production is still free to execute and hand the original passport to Sewing.
    result = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    assert result.status_code == 201, result.text


def test_cutting_correction_cannot_be_bypassed_by_resubmitting_costs(client, auth_headers):
    data = setup(client, "cut-correction")
    request = submit(client, data, "accessories", submit(client, data, "purchasing", save_costs(client, data)))
    base = f"/api/price-calculation/requests/{request['id']}"
    returned = client.post(base + "/return", headers=auth_headers,
        json={"expected_revision": request["revision"], "team": "cutting", "reason": "Correct the consumption"})
    assert returned.status_code == 200, returned.text
    bypass = submit(client, data, "purchasing", returned.json())
    assert bypass["workflow_state"] == "collecting" and bypass["correction_team"] == "cutting"
    assert client.post(base + "/approve", headers=auth_headers, json={"expected_revision": bypass["revision"], "selling_price": 6}).status_code == 409
    changed = client.patch(f"/api/cutting-passports/{data['passport']['id']}", headers=data["cutting"], json=data["payload"] | {"lay_length_m": 5})
    assert changed.status_code == 200, changed.text
    refreshed = get_request(client, data)
    assert refreshed["correction_team"] is None
    assert refreshed["purchasing_submitted_at"] is None and refreshed["accessories_submitted_at"] is None


def test_external_price_recovers_stale_slot_and_priced_reprice_is_refused(client, auth_headers):
    data = setup(client, "slot-recovery")
    with SessionLocal() as db:
        model = db.get(Model, data["model_id"])
        model.selling_price = 7
        model.selling_price_currency = "USD"
        model.selling_price_source = "import"
        db.commit()
    saved = client.post("/api/cutting-passports", headers=data["cutting"], json=data["payload"] | {"passport_no": "IMPORTED-REUSE"})
    assert saved.status_code == 201, saved.text
    with SessionLocal() as db:
        assert db.get(PriceCalculationRequest, data["request_id"]).workflow_state == "cancelled"
        assert db.query(PriceCalculationRequest).filter_by(active_model_id=data["model_id"]).count() == 0
    revision = client.post(f"/api/price-calculation/models/{data['model_id']}/reprice", headers=auth_headers, json={"reason": "New seasonal costs"})
    assert revision.status_code == 409, revision.text
    with SessionLocal() as db:
        assert db.query(PriceCalculationRequest).filter_by(model_id=data["model_id"]).count() == 1
    with SessionLocal() as db:
        assert db.get(Model, data["model_id"]).selling_price == 7


def test_unused_passport_deletion_preserves_approved_price_and_snapshot(client, auth_headers):
    data = setup(client, "delete-source")
    request = submit(client, data, "accessories", submit(client, data, "purchasing", save_costs(client, data)))
    approved = client.post(f"/api/price-calculation/requests/{request['id']}/approve", headers=auth_headers, json={"expected_revision": request["revision"], "selling_price": 6})
    assert approved.status_code == 200, approved.text
    removed = client.delete(f"/api/cutting-passports/{data['passport']['id']}", headers=data["cutting"])
    assert removed.status_code == 204, removed.text
    with SessionLocal() as db:
        saved = db.get(PriceCalculationRequest, request["id"])
        assert saved.workflow_state == "approved" and saved.cutting_passport_id is None
        assert saved.approval_snapshot_json["cutting_passport_id"] == data["passport"]["id"]
        assert db.get(Model, data["model_id"]).selling_price == 6


def test_unresolved_or_unauthorized_passport_identity_does_not_block_cutting_or_create_task(client, auth_headers):
    with SessionLocal() as db:
        model = Model(code="RESTRICTED-USLUGA", name="Customer model", catalog_scope="usluga", factory_code="ECO", status="approved")
        db.add(model); db.commit(); model_id = model.id
    saved = client.post("/api/cutting-passports", headers=auth_headers, json={"passport_no": "UNAUTHORIZED-PRICING-SOURCE", "date": "2026-11-10T00:00:00Z", "model_code": "RESTRICTED-USLUGA"})
    assert saved.status_code == 201, saved.text
    with SessionLocal() as db:
        assert db.query(PriceCalculationRequest).filter_by(model_id=model_id).count() == 0


def test_excel_exports_all_filtered_rows_and_neutralizes_formula_text(client, auth_headers):
    with SessionLocal() as db:
        db.add_all([Model(code=f"EXPORT-FULL-{index:03}", name="=SUM(1,2)" if index == 0 else f"Export {index}", status="approved", selling_price=1.25, selling_price_currency="USD", selling_price_source="import") for index in range(65)])
        db.commit()
    page = client.get("/api/price-calculation/report?q=EXPORT-FULL&limit=50", headers=auth_headers)
    assert page.status_code == 200 and len(page.json()) == 50
    exported = client.get("/api/price-calculation/report.xlsx?q=EXPORT-FULL", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    sheet = load_workbook(BytesIO(exported.content))["Variant Prices"]
    assert sheet.max_row == 66
    assert all(sheet.cell(row, 5).value == 1.25 for row in range(2, 67))
    assert any(sheet.cell(row, 3).value == "'=SUM(1,2)" for row in range(2, 67))
    assert all(cell.data_type != "f" for row in sheet for cell in row)


def test_pending_filter_runs_before_pagination(client):
    data = setup(client, "page-filter")
    with SessionLocal() as db:
        actor_id = db.query(User.id).filter_by(email="abbosbek.price.page-filter@example.com").scalar()
        for index in range(55):
            model = Model(code=f"PAGINATION-{index}", name="Completed purchasing", status="approved")
            db.add(model); db.flush()
            db.add(PriceCalculationRequest(model_id=model.id, active_model_id=model.id, factory_code="MIL", workflow_state="collecting", created_by_id=actor_id, purchasing_submitted_at=datetime.now(timezone.utc)))
        db.commit()
    pending = client.get("/api/price-calculation/requests?queue=pending&team=purchasing&limit=50", headers=data["purchasing"])
    assert pending.status_code == 200, pending.text
    assert [row["id"] for row in pending.json()] == [data["request_id"]]


def test_cross_factory_kroy_cannot_be_bound_to_milana_pricing(client):
    from app.schemas import Department, ProductionOrder, WorkOrder
    data = setup(client, "foreign-kroy")
    with SessionLocal() as db:
        order = ProductionOrder(production_no="PO-FOREIGN-KROY", production_type="branded_stock", model_id=data["model_id"], planned_quantity=10)
        db.add(order); db.flush()
        dept_id = db.query(Department.id).filter_by(code="ECT").scalar()
        db.add(WorkOrder(production_order_id=order.id, department_id=dept_id, operation="cutting", status="in_progress", planned_output_qty=10))
        passport = CuttingPassport(passport_no="ECO-ONLY-KROY", date=datetime.now(timezone.utc), production_order_id=order.id,
            model_code=db.get(Model, data["model_id"]).code, size_range="S, M", fabric_width_m=9, lay_length_m=9, gramage=.2)
        db.add(passport); db.commit()
    response = client.patch(f"/api/price-calculation/requests/{data['request_id']}/cutting", headers=data["cutting"], json={"kroy_no": "ECO-ONLY-KROY"})
    assert response.status_code == 409, response.text
    assert get_request(client, data)["cutting_passport_id"] == data["passport"]["id"]


def test_reconciliation_preview_is_read_only_and_apply_is_idempotent(client, auth_headers):
    from scripts.reconcile_variant_pricing import reconcile
    data = _setup_workflow_data("reconcile")
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        before = (db.query(PriceCalculationRequest).count(), db.query(AuditLog).count(), db.query(Notification).count())
        preview = reconcile(db, actor)
        assert any(row["model"] == "PC-TEST-reconcile-GRAY" and row["action"] == "create_request" for row in preview)
        assert (db.query(PriceCalculationRequest).count(), db.query(AuditLog).count(), db.query(Notification).count()) == before
        facts = protected_facts(db)
        reconcile(db, actor, apply=True)
        assert protected_facts(db) == facts
        count = db.query(PriceCalculationRequest).filter_by(model_id=data["model_id"]).count()
        assert count == 1
        reconcile(db, actor, apply=True)
        assert db.query(PriceCalculationRequest).filter_by(model_id=data["model_id"]).count() == count


def test_deleting_cancelled_source_never_revives_it_even_with_replacement(client, auth_headers):
    data = setup(client, "cancel-delete")
    request = get_request(client, data)
    cancelled = client.post(f"/api/price-calculation/requests/{request['id']}/cancel", headers=auth_headers,
        json={"expected_revision": request["revision"], "reason": "Duplicate historic costing"})
    assert cancelled.status_code == 200, cancelled.text
    removed = client.delete(f"/api/cutting-passports/{data['passport']['id']}", headers=data["cutting"])
    assert removed.status_code == 204, removed.text
    with SessionLocal() as db:
        saved = db.get(PriceCalculationRequest, request["id"])
        assert saved.workflow_state == "cancelled" and saved.active_model_id is None and saved.cutting_passport_id is None


def test_moving_standalone_passport_retires_old_variant_request(client):
    data = setup(client, "move-identity")
    with SessionLocal() as db:
        model = Model(code="MOVE-NEW-VARIANT", name="Another variant", status="approved")
        db.add(model); db.commit(); new_model_id = model.id
    changed = client.patch(f"/api/cutting-passports/{data['passport']['id']}", headers=data["cutting"],
        json=data["payload"] | {"model_code": "MOVE-NEW-VARIANT"})
    assert changed.status_code == 200, changed.text
    with SessionLocal() as db:
        old = db.get(PriceCalculationRequest, data["request_id"])
        assert old.workflow_state == "cancelled" and old.active_model_id is None and old.cutting_passport_id is None
        new = db.query(PriceCalculationRequest).filter_by(active_model_id=new_model_id).one()
        assert new.cutting_passport_id == data["passport"]["id"]


def test_cached_passport_relation_uses_new_order_identity_and_printing(client):
    from app.models.planning.variant_pricing_service import sync_passport_pricing
    from app.schemas import Department, ProductionOrder, ProductionOrderItem, WorkOrder

    data = setup(client, "cached-order")
    with SessionLocal() as db:
        model = Model(code="CACHED-ORDER-NEW", name="New order variant", status="approved")
        db.add(model); db.flush()
        order = ProductionOrder(production_no="PO-CACHED-NEW", production_type="branded_stock", model_id=model.id, planned_quantity=10)
        db.add(order); db.flush()
        db.add(ProductionOrderItem(production_order_id=order.id, model_id=model.id, color="Blue", size="S", planned_quantity=10, printing_required=True))
        db.add(WorkOrder(production_order_id=order.id, department_id=db.query(Department.id).filter_by(code="CUT").scalar(), operation="cutting", status="in_progress", planned_output_qty=10))
        db.flush()
        passport = db.get(CuttingPassport, data["passport"]["id"])
        assert passport.production_order is None  # Intentionally populate the stale relationship cache.
        passport.production_order_id = order.id
        passport.model_code = model.code
        actor = db.query(User).filter_by(email="cutting.price.cached-order@example.com").one()
        facts = protected_facts(db)
        sync_passport_pricing(db, passport, actor)
        assert protected_facts(db) == facts
        old = db.get(PriceCalculationRequest, data["request_id"])
        assert old.workflow_state == "cancelled" and old.cutting_passport_id is None
        request = db.query(PriceCalculationRequest).filter_by(active_model_id=model.id).one()
        assert request.passport_snapshot_json["production_order_id"] == order.id
        assert request.passport_snapshot_json["has_print"] is True


@pytest.mark.parametrize("rate", [0, 5])
def test_one_fabric_price_covers_all_consumption_and_binding_rows(client, rate):
    data = setup(client, f"shared-rate-{rate}")
    with SessionLocal() as db:
        passport = db.get(CuttingPassport, data["passport"]["id"])
        passport.order_no = "ORDER-SHARED-PRICE"
        passport.materials = [
            {"stock_batch_id": 101, "fabric_type": "Main", "size_range": "S, M", "fabric_width_m": 2, "lay_length_m": 4, "gramage": .2, "beka_per_piece_kg": .01},
            {"stock_batch_id": 102, "fabric_type": "Contrast", "size_range": "S, M", "fabric_width_m": 2, "lay_length_m": 2, "gramage": .2, "beka_per_piece_kg": .02},
        ]
        from app.models.planning.variant_pricing_service import sync_passport_pricing
        sync_passport_pricing(db, passport, db.query(User).filter_by(email=f"cutting.price.shared-rate-{rate}@example.com").one())
        db.commit()
        before = protected_facts(db)
    request = get_request(client, data)
    assert request["order_no"] == "ORDER-SHARED-PRICE"
    assert [row["consumption"] for row in request["materials"]] == [.8, .01, .4, .02]
    base = f"/api/price-calculation/requests/{request['id']}"
    saved = client.patch(base + "/purchasing", headers=data["purchasing"], json={
        "expected_revision": request["revision"], "fabric_price": rate, "sewing_cost": .5})
    assert saved.status_code == 200, saved.text
    assert all(row["rate"] == rate for row in saved.json()["materials"])
    assert saved.json()["cost_price"] is None
    stale = client.patch(base + "/purchasing", headers=data["purchasing"], json={"expected_revision": request["revision"], "fabric_price": 99})
    assert stale.status_code == 409
    saved = client.patch(base + "/accessories", headers=data["accessories"], json={
        "expected_revision": saved.json()["revision"], "accessories": [], "no_accessories_reason": "No trims needed"})
    assert saved.status_code == 200
    request = submit(client, data, "purchasing", saved.json())
    request = submit(client, data, "accessories", request)
    assert request["consumption_cost"] == pytest.approx(1.23 * rate)
    assert request["cost_price"] == pytest.approx(1.23 * rate + .6)
    with SessionLocal() as db:
        assert db.get(Model, data["model_id"]).selling_price is None
        assert protected_facts(db) == before


def test_price_card_order_number_uses_linked_order_and_freezes_on_approval(client, auth_headers):
    from app.schemas import ProductionOrder
    data = setup(client, "order-label")
    sales = client.post("/api/sales-orders", headers=auth_headers, json={"items": [
        {"model_id": data["model_id"], "color": "gray", "size": "S", "quantity": 2, "unit_price": 1.25}]})
    assert sales.status_code == 201, sales.text
    with SessionLocal() as db:
        order = ProductionOrder(production_no="PO-PRICE-LABEL", production_type="client_order", model_id=data["model_id"], sales_order_id=sales.json()["id"], planned_quantity=2)
        db.add(order); db.flush()
        passport = db.get(CuttingPassport, data["passport"]["id"])
        passport.production_order_id = order.id
        passport.order_no = "STALE-MANUAL-LABEL"
        db.flush()
        db.expire(passport, ["production_order"])
        from app.models.planning.variant_pricing_service import snapshot_passport
        snapshot_passport(db, db.get(PriceCalculationRequest, data["request_id"]), passport)
        db.commit()
    request = get_request(client, data)
    assert request["order_no"] == sales.json()["order_no"]
    request = save_costs(client, data)
    request = submit(client, data, "purchasing", request)
    request = submit(client, data, "accessories", request)
    approved = client.post(f"/api/price-calculation/requests/{request['id']}/approve", headers=auth_headers,
        json={"expected_revision": request["revision"], "selling_price": 6})
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        saved = db.get(PriceCalculationRequest, request["id"])
        assert saved.approval_snapshot_json["order_no"] == sales.json()["order_no"]
        db.get(ProductionOrder, order.id).sales_order_id = None
        db.commit()
    assert get_request(client, data)["order_no"] == sales.json()["order_no"]

from decimal import Decimal

import pytest

from app.db.session import SessionLocal
from app.schemas import AuditLog, CuttingRecord, Department, Item, MaterialReservation, ModelBOM, ProductionOrder, SalesOrder, SalesOrderItem, StockBatch, StockMovement, User, WorkOrder
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.tests.eco_fabric_fixture import make_eco_fabric_case, planning_payload


@pytest.fixture
def eco_case():
    return make_eco_fabric_case(SessionLocal)


def test_milana_planning_lookup_has_real_eco_stock_and_never_writes(client, eco_case):
    with SessionLocal() as db:
        before = (db.query(StockBatch).count(), db.query(StockMovement).count(), db.query(EcoMaterialMovement).count())
    for _ in range(3):
        result = client.get("/api/planning/eco-fabrics", headers=eco_case["mil_headers"])
        assert result.status_code == 200, result.text
        row = next(row for row in result.json() if row["eco_material_batch_id"] == eco_case["receipt"])
        assert row["id"] is None and row["available_quantity"] == 90 and row["quantity"] == 100 and row["reserved_quantity"] == 10
        assert "cost_per_unit" not in row
    assert client.get("/api/eco-inventory/stock", headers=eco_case["mil_headers"]).status_code == 403
    with SessionLocal() as db:
        assert (db.query(StockBatch).count(), db.query(StockMovement).count(), db.query(EcoMaterialMovement).count()) == before
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).source_stock_batch_id is None


def test_direct_eco_planning_passport_spend_retry_delete_conserves_ledgers(client, eco_case):
    created = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=planning_payload(eco_case))
    assert created.status_code == 201, created.text
    order = created.json()
    source_id = order["fabric_batch_id"]
    assert order["materials"][0]["stock_batch_id"] == source_id
    with SessionLocal() as db:
        receipt = db.get(EcoMaterialBatch, eco_case["receipt"])
        assert receipt.source_stock_batch_id == source_id and receipt.quantity == 100 and receipt.reserved_quantity == 10
        assert db.get(StockBatch, source_id).quantity == 0
        assert db.query(StockMovement).filter_by(batch_id=source_id).count() == 0
        assert db.query(MaterialReservation).filter_by(stock_batch_id=source_id).count() == 0
        work_id = db.query(WorkOrder).filter_by(production_order_id=order["id"], operation="cutting").one().id
    passport = client.post("/api/cutting-passports", headers=eco_case["eco_headers"], json={
        "date": "2026-11-13T00:00:00Z", "production_order_id": order["id"],
        "materials": [{"stock_batch_id": source_id, "layer_weight_kg": 2, "total_layers": 3, "scrap_kg": .5, "pieces": 10}],
    })
    assert passport.status_code == 201, passport.text
    saved = passport.json()
    payload = {"work_order_id": work_id, "cutting_passport_id": saved["id"], "production_batch_id": saved["production_batch_id"],
        "use_passport_materials": True, "input_quantity": 0, "cut_pieces": 10, "passed_pieces": 10,
        "bundles": [{"color": "white", "size": "46", "quantity": 10, "count": 1, "next": "sewing", "sewing_factory": "eco_cotton"}]}
    cut = client.post("/api/cutting/records", headers=eco_case["eco_headers"], json=payload)
    assert cut.status_code == 201, cut.text
    assert client.post("/api/cutting/records", headers=eco_case["eco_headers"], json=payload).status_code in (400, 409)
    with SessionLocal() as db:
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).quantity == Decimal("93.5")
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).reserved_quantity == 10
        assert db.get(StockBatch, source_id).quantity == 0
        assert db.query(StockMovement).filter_by(batch_id=source_id).count() == 0
        assert db.query(EcoMaterialMovement).filter_by(batch_id=eco_case["receipt"], kind="consume").count() == 1
    removed = client.delete(f"/api/work-orders/{work_id}/batches/{saved['production_batch_id']}", headers=eco_case["eco_headers"])
    assert removed.status_code == 200, removed.text
    with SessionLocal() as db:
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).quantity == 100
        assert db.get(StockBatch, source_id).quantity == 0


@pytest.mark.parametrize("change", [
    {"cutting_department_code": "CUT"},
    {"materials": [{"eco_material_batch_id": -1, "estimated_quantity": 8, "unit": "kg"}]},
    {"model_id": 99999999},
    {"materials": [{"eco_material_batch_id": "receipt", "estimated_quantity": 95, "unit": "kg"}]},
    {"materials": [{"eco_material_batch_id": "receipt", "estimated_quantity": 8, "unit": "m"}]},
])
def test_failed_planning_keeps_direct_receipt_unlinked_and_balances_unchanged(client, eco_case, change):
    change = {**change}
    if "materials" in change:
        change["materials"] = [{**row, "eco_material_batch_id": eco_case["receipt"] if row["eco_material_batch_id"] == "receipt"
                                else row["eco_material_batch_id"]} for row in change["materials"]]
    with SessionLocal() as db:
        before = db.query(StockBatch).count(), db.query(ProductionOrder).count()
    result = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=planning_payload(eco_case, **change))
    assert result.status_code in (400, 404, 409, 422), result.text
    with SessionLocal() as db:
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).source_stock_batch_id is None
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).quantity == 100
        assert (db.query(StockBatch).count(), db.query(ProductionOrder).count()) == before
        assert db.query(CuttingRecord).count() == 0


@pytest.mark.parametrize("field,value", [("quantity", 10), ("receipt_details", {"qc_status": "pending"})])
def test_reserved_or_held_source_cannot_be_selected(client, eco_case, field, value):
    with SessionLocal() as db:
        setattr(db.get(EcoMaterialBatch, eco_case["receipt"]), field, value)
        db.commit()
    response = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=planning_payload(eco_case))
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).source_stock_batch_id is None


@pytest.mark.parametrize("valid", [True, False])
def test_passport_can_add_direct_eco_receipt_atomically_and_reopen_canonical_ids(client, eco_case, valid):
    created = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"],
        json=planning_payload(eco_case, materials=[], eco_fabric_batch_id=None, estimated_material_amount=None))
    assert created.status_code == 201, created.text
    order = created.json()
    lookup = client.get("/api/cutting-passports/material-batches", headers=eco_case["eco_headers"],
                        params={"production_order_id": order["id"]})
    assert lookup.status_code == 200, lookup.text
    assert any(row["id"] is None and row["eco_material_batch_id"] == eco_case["receipt"] for row in lookup.json())
    payload = {"date": "2026-11-13T00:00:00Z", "production_order_id": order["id"],
        "materials": [{"eco_material_batch_id": eco_case["receipt"], "planned_kg": 8, "pieces": 10}],
        "additional_materials": [{"eco_material_batch_id": eco_case["receipt"], "estimated_quantity": 8,
                                  "unit": "kg" if valid else "m"}]}
    result = client.post("/api/cutting-passports", headers=eco_case["eco_headers"], json=payload)
    assert result.status_code == (201 if valid else 400), result.text
    with SessionLocal() as db:
        source_id = db.get(EcoMaterialBatch, eco_case["receipt"]).source_stock_batch_id
        assert bool(source_id) == valid
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).quantity == 100
        if valid:
            assert db.get(StockBatch, source_id).quantity == 0
            assert db.query(MaterialReservation).filter_by(stock_batch_id=source_id).count() == 0
    if valid:
        saved = result.json()
        assert saved["materials"][0]["stock_batch_id"] == source_id
        assert "eco_material_batch_id" not in saved["materials"][0]
        reopened = client.get(f"/api/cutting-passports/{saved['id']}", headers=eco_case["eco_headers"])
        assert reopened.status_code == 200 and reopened.json()["materials"] == saved["materials"]
        # Original explicit-source form can retry without a second identity.
        assert client.patch(f"/api/cutting-passports/{saved['id']}", headers=eco_case["eco_headers"], json=payload).status_code == 200


def test_api_cannot_override_trusted_eco_balance_or_supply_two_source_types(client, eco_case):
    payload = planning_payload(eco_case, materials=[{"eco_material_batch_id": eco_case["receipt"],
        "estimated_quantity": 91, "unit": "kg"}], eco_fabric_available={str(eco_case["receipt"]): 1000000})
    rejected = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=payload)
    assert rejected.status_code == 409, rejected.text
    payload["materials"][0].update(stock_batch_id=1, estimated_quantity=1)
    assert client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=payload).status_code == 422


def test_linked_eco_receipt_still_rejects_milana_cutting_and_uses_physical_eco_availability(client, eco_case):
    created = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=planning_payload(eco_case))
    assert created.status_code == 201, created.text
    source_id = created.json()["fabric_batch_id"]
    with SessionLocal() as db:
        db.get(EcoMaterialBatch, eco_case["receipt"]).quantity = 11
        db.commit()
    payload = planning_payload(eco_case, eco_fabric_batch_id=None, fabric_batch_id=source_id,
                              materials=[{"stock_batch_id": source_id, "estimated_quantity": 8, "unit": "kg"}])
    rejected = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=payload)
    assert rejected.status_code == 409, rejected.text
    payload.update(cutting_department_code="CUT")
    assert client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=payload).status_code == 400


def test_explicit_destination_planning_denial_is_not_bypassed(client, eco_case):
    with SessionLocal() as db:
        db.get(User, eco_case["planner"]).access_policy = {"ECO": {"deny": ["planning.production"]}}
        db.commit()
    assert client.get("/api/planning/eco-fabrics", headers=eco_case["mil_headers"]).status_code == 403
    rejected = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=planning_payload(eco_case))
    assert rejected.status_code == 403, rejected.text
    with SessionLocal() as db:
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).source_stock_batch_id is None


def test_first_material_authority_does_not_assign_unused_primary_receipt(client, eco_case):
    with SessionLocal() as db:
        other = EcoMaterialBatch(item_id=eco_case["item"], kind="fabric", batch_no="OTHER-DIRECT", color="white",
            unit="kg", quantity=50, reserved_quantity=0, created_by=eco_case["operator"])
        db.add(other); db.flush(); other_id = other.id
        db.add(EcoMaterialMovement(batch_id=other_id, kind="receive", quantity=50, created_by=eco_case["operator"]))
        db.commit()
    payload = planning_payload(eco_case, materials=[{"eco_material_batch_id": other_id, "estimated_quantity": 8, "unit": "kg"}])
    created = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=payload)
    assert created.status_code == 201, created.text
    with SessionLocal() as db:
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).source_stock_batch_id is None
        assert db.query(StockBatch).filter_by(internal_batch_no=f"ECO-DIRECT-{eco_case['receipt']}").count() == 0
        assert db.query(AuditLog).filter_by(entity_type="EcoMaterialBatch", entity_id=eco_case["receipt"], action="assign_cutting_identity").count() == 0
        assert db.get(EcoMaterialBatch, other_id).source_stock_batch_id == created.json()["fabric_batch_id"]


def test_search_keeps_complete_linked_balance_and_searches_displayed_source_labels(client, eco_case):
    created = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=planning_payload(eco_case))
    assert created.status_code == 201, created.text
    source_id = created.json()["fabric_batch_id"]
    with SessionLocal() as db:
        source = db.get(StockBatch, source_id)
        source.batch_no = "DISPLAYED-CENTRAL-LOT"
        source.color = "SEARCHABLE-COLOUR"
        other = EcoMaterialBatch(item_id=eco_case["item"], kind="fabric", batch_no="SECOND-PHYSICAL-RECEIPT",
            unit="kg", quantity=20, reserved_quantity=0, created_by=eco_case["operator"], source_stock_batch_id=source_id)
        db.add(other); db.commit()
    for query in (eco_case["batch_no"], "SECOND-PHYSICAL", "DISPLAYED-CENTRAL", "SEARCHABLE-COLOUR"):
        result = client.get("/api/planning/eco-fabrics", headers=eco_case["mil_headers"], params={"q": query})
        assert result.status_code == 200, result.text
        row = next(row for row in result.json() if row["id"] == source_id)
        assert row["quantity"] == 120 and row["available_quantity"] == 110
        assert row["color"] == "SEARCHABLE-COLOUR"


def test_cutting_lookup_reports_actual_reservations_separately_from_quality_holds(client, eco_case):
    created = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"], json=planning_payload(eco_case))
    assert created.status_code == 201, created.text
    source_id = created.json()["fabric_batch_id"]
    with SessionLocal() as db:
        db.add_all([EcoMaterialBatch(item_id=eco_case["item"], kind="fabric", batch_no=label, unit="kg",
            quantity=quantity, reserved_quantity=reserved, source_stock_batch_id=source_id, created_by=eco_case["operator"],
            receipt_details={"qc_status": qc}) for label, quantity, reserved, qc in (
                ("PASSED-RESERVED", 20, 3, "passed"), ("ON-QUALITY-HOLD", 50, 0, "pending"))])
        db.commit()
    lookup = client.get("/api/cutting-passports/material-batches", headers=eco_case["eco_headers"],
                        params={"production_order_id": created.json()["id"]})
    assert lookup.status_code == 200, lookup.text
    row = next(row for row in lookup.json() if row["id"] == source_id)
    assert row["quantity"] == 170 and row["reserved_quantity"] == 13 and row["available_quantity"] == 107
    with SessionLocal() as db:
        assert db.get(StockBatch, source_id).quantity == 0
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).reserved_quantity == 10


def test_client_modal_primary_only_eco_source_passport_and_cut_use_selected_fabric(client, eco_case):
    with SessionLocal() as db:
        sale = SalesOrder(order_no=f"QA-ECO-SO-{eco_case['batch_no']}", status="confirmed", order_type="client_order", created_by=eco_case["planner"])
        unrelated = Item(sku=f"QA-OTHER-{eco_case['item']}", name="Unrelated BOM fabric", category="fabric", unit="kg")
        db.add_all([sale, unrelated]); db.flush(); sale_id = sale.id
        db.add(SalesOrderItem(sales_order_id=sale_id, model_id=eco_case["model"], brand_id=eco_case["brand"],
                             color="white", size="46", quantity=10, unit_price=1))
        db.add(ModelBOM(model_id=eco_case["model"], item_id=unrelated.id, quantity_per_piece=.5, unit="kg"))
        db.commit()
    payload = planning_payload(eco_case, production_type="client_order", sales_order_id=sale_id, materials=[])
    created = client.post("/api/planning/create-production-order", headers=eco_case["mil_headers"], json=payload)
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["materials"] == [] and order["fabric_batch_id"]
    source_id = order["fabric_batch_id"]
    defaults = client.get("/api/cutting-passports/material-defaults", headers=eco_case["eco_headers"],
                          params={"production_order_id": order["id"]})
    assert defaults.status_code == 200, defaults.text
    assert [row["stock_batch_id"] for row in defaults.json()["materials"]] == [source_id]
    passport = client.post("/api/cutting-passports", headers=eco_case["eco_headers"], json={
        "date": "2026-11-13T00:00:00Z", "production_order_id": order["id"],
        "materials": [{"stock_batch_id": source_id, "planned_kg": 8, "layer_weight_kg": 2, "total_layers": 3, "scrap_kg": .5,
                       "pieces": 10, "rolls_count": 1}],
    })
    assert passport.status_code == 201, passport.text
    saved = passport.json()
    assert client.get(f"/api/cutting-passports/{saved['id']}", headers=eco_case["eco_headers"]).json()["materials"][0]["stock_batch_id"] == source_id
    with SessionLocal() as db:
        work_id = db.query(WorkOrder).filter_by(production_order_id=order["id"], operation="cutting").one().id
    cut = client.post("/api/cutting/records", headers=eco_case["eco_headers"], json={
        "work_order_id": work_id, "cutting_passport_id": saved["id"], "production_batch_id": saved["production_batch_id"],
        "use_passport_materials": True, "input_quantity": 0, "cut_pieces": 10, "passed_pieces": 10,
        "bundles": [{"color": "white", "size": "46", "quantity": 10, "count": 1, "next": "sewing", "sewing_factory": "eco_cotton"}],
    })
    assert cut.status_code == 201, cut.text
    with SessionLocal() as db:
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).quantity == Decimal("93.5")
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).reserved_quantity == 10
        assert db.get(StockBatch, source_id).quantity == 0
        assert db.query(StockMovement).filter_by(batch_id=source_id).count() == 0


def test_unrecognized_cutting_department_cannot_resolve_direct_eco_source(client, eco_case):
    created = client.post("/api/planning/create-branded-production", headers=eco_case["mil_headers"],
        json=planning_payload(eco_case, materials=[], eco_fabric_batch_id=None, estimated_material_amount=None))
    assert created.status_code == 201, created.text
    with SessionLocal() as db:
        department = Department(code="CUSTOM-CUTTING", name="Legacy configurable cutting department")
        db.add(department); db.flush()
        db.query(WorkOrder).filter_by(production_order_id=created.json()["id"], operation="cutting").one().department_id = department.id
        db.commit()
    rejected = client.post("/api/cutting-passports", headers=eco_case["eco_headers"], json={
        "date": "2026-11-13T00:00:00Z", "production_order_id": created.json()["id"],
        "materials": [{"eco_material_batch_id": eco_case["receipt"], "planned_kg": 8, "pieces": 10}],
        "additional_materials": [{"eco_material_batch_id": eco_case["receipt"], "estimated_quantity": 8, "unit": "kg"}],
    })
    assert rejected.status_code == 400 and "requires Eco Cotton Cutting" in rejected.text
    with SessionLocal() as db:
        assert db.get(EcoMaterialBatch, eco_case["receipt"]).source_stock_batch_id is None


@pytest.mark.parametrize("source_field", ["primary", "materials"])
def test_generic_production_api_explicitly_refuses_unresolved_eco_inputs_without_writes(client, eco_case, source_field):
    payload = planning_payload(eco_case, **({"materials": []} if source_field == "primary" else {"eco_fabric_batch_id": None}))
    with SessionLocal() as db:
        before = tuple(db.query(table).count() for table in (ProductionOrder, WorkOrder, StockBatch, StockMovement, EcoMaterialMovement, AuditLog))
    response = client.post("/api/production-orders", headers=eco_case["mil_headers"], json=payload)
    assert response.status_code == 400 and "through Planning" in response.text, response.text
    with SessionLocal() as db:
        assert tuple(db.query(table).count() for table in (ProductionOrder, WorkOrder, StockBatch, StockMovement, EcoMaterialMovement, AuditLog)) == before
        receipt = db.get(EcoMaterialBatch, eco_case["receipt"])
        assert receipt.source_stock_batch_id is None and receipt.quantity == 100 and receipt.reserved_quantity == 10

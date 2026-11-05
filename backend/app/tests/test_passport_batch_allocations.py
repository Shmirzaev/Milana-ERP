"""One calculation, exact source batches; all fixtures are synthetic."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.schemas import Bundle, CuttingMaterialUsage, CuttingPassport, CuttingRecord, Department, MaterialReservation, ProductionOrder, ProductionOrderMaterial, StockBatch, StockMovement, Warehouse, WasteRecord, WorkOrder
from app.tests.test_material_reservations import _warehouse, _fabric_item, _receive_batch, _cutting_work_order


@pytest.fixture
def allocation_case(client, auth_headers):
    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    item = _fabric_item(client, auth_headers)
    batches = [_receive_batch(client, auth_headers, item_id=item["id"], warehouse_id=warehouse["id"], quantity=quantity, unit="kg") for quantity in (150, 250)]
    with SessionLocal() as db:
        for index, row in enumerate(batches):
            batch = db.get(StockBatch, row["id"])
            batch.batch_no = f"QA-SPLIT-{uuid4().hex[:6]}-{'A' if index == 0 else 'B'}"
            batch.color = "red"
            batch.width = 1.6
            batch.gsm = .18
        db.commit()
    created = client.post("/api/planning/create-branded-production", headers=auth_headers, json={
        "production_type": "branded_stock", "model_id": 1, "planned_quantity": 600,
        "materials": [{"stock_batch_id": row["id"], "estimated_quantity": quantity, "unit": "kg"} for row, quantity in zip(batches, (100, 200))],
        "items": [{"model_id": 1, "color": "red", "size": "46", "planned_quantity": 600}],
    })
    assert created.status_code == 201, created.text
    oid = created.json()["id"]
    work = _cutting_work_order(client, auth_headers, oid)
    material = {"stock_batch_id": batches[0]["id"], "batch_allocations": [
        {"stock_batch_id": row["id"], "quantity": quantity, "batch_no": "untrusted label"} for row, quantity in zip(batches, (100, 200))],
        "layer_weight_kg": 3, "total_layers": 100, "planned_kg": 999, "pieces": 600,
        "rolls_count": 3, "waste_pct": 10, "beka_per_piece_kg": .01, "operator_name_manual": "QA layup"}
    payload = {"passport_no": "QA-GROUP-" + uuid4().hex[:8], "date": "2026-11-05T00:00:00Z",
               "production_order_id": oid, "materials": [material]}
    return {"order_id": oid, "work_id": work["id"], "batches": [row["id"] for row in batches], "payload": payload,
            "warehouse": warehouse, "item": item}


def save(client, auth, case, payload=None):
    return client.post("/api/cutting-passports", headers=auth, json=payload or case["payload"])


def confirm(client, auth, case, passport):
    return client.post("/api/cutting/records", headers=auth, json={
        "work_order_id": case["work_id"], "production_batch_id": passport["production_batch_id"],
        "cutting_passport_id": passport["id"], "use_passport_materials": True, "input_quantity": 0,
        "cut_pieces": 600, "passed_pieces": 600,
        "bundles": [{"color": "red", "size": "46", "quantity": 600, "count": 1, "next": "sewing", "sewing_factory": "milana"}],
    })


def test_one_group_saves_without_debit_then_consumes_100_and_200_exactly_once(client, auth_headers, allocation_case):
    case = allocation_case
    response = save(client, auth_headers, case)
    assert response.status_code == 201, response.text
    passport = response.json()
    assert len(passport["materials"]) == 1
    assert passport["materials"][0]["actual_kg"] == passport["actual_kg"] == 300
    assert [part["quantity"] for part in passport["materials"][0]["batch_allocations"]] == [100, 200]
    assert all(part["batch_no"] != "untrusted label" for part in passport["materials"][0]["batch_allocations"])
    with SessionLocal() as db:
        assert [float(db.get(StockBatch, bid).quantity) for bid in case["batches"]] == [150, 250]
        assert not db.query(StockMovement).filter(StockMovement.movement_type == "consume", StockMovement.batch_id.in_(case["batches"])).first()
    cut = confirm(client, auth_headers, case, passport)
    assert cut.status_code == 201, cut.text
    assert [row["quantity"] for row in cut.json()["materials"]] == [100, 200]
    assert confirm(client, auth_headers, case, passport).status_code == 409
    with SessionLocal() as db:
        assert [float(db.get(StockBatch, bid).quantity) for bid in case["batches"]] == [50, 50]
        usages = db.query(CuttingMaterialUsage).filter_by(cutting_record_id=cut.json()["id"]).all()
        assert sum(row.details["cut_pieces"] for row in usages) == 600
        assert sum(row.details["material_rolls_used"] for row in usages) == 3
        assert sum(row.details["waste_quantity"] for row in usages) == 30
        assert sum(float(row.quantity) for row in db.query(WasteRecord).filter_by(work_order_id=case["work_id"])) == 30
        assert db.get(WorkOrder, case["work_id"]).passed_qty == 600
        assert db.query(Bundle).filter_by(production_order_id=case["order_id"]).one().quantity == 600
        assert db.query(CuttingRecord).filter_by(work_order_id=case["work_id"]).count() == 1
    sheet = client.get(f"/api/cutting/records/{cut.json()['id']}/production-sheet", headers=auth_headers)
    assert sheet.status_code == 200, sheet.text
    assert "300 kg" in sheet.text
    for part in passport["materials"][0]["batch_allocations"]: assert part["batch_no"] in sheet.text
    dashboard = client.get("/api/cutting-passports/dashboard?date_from=2026-11-05&date_to=2026-11-05", headers=auth_headers)
    assert dashboard.status_code == 200 and dashboard.json()["totals"]["pieces"] == 600
    assert dashboard.json()["totals"]["fabric_kg"] == 300


@pytest.mark.parametrize("problem,status", [("sum", 400), ("duplicate", 422), ("missing_anchor", 422), ("one_source", 422),
    ("zero", 422), ("precision", 422), ("nan", 422), ("cross_group", 400), ("color", 400), ("width", 400),
    ("gsm", 400), ("unit", 400), ("item", 400), ("unassigned", 400), ("shortage", 409)])
def test_group_refusals_preserve_stock_and_passports(client, auth_headers, allocation_case, problem, status):
    case = allocation_case
    payload = deepcopy(case["payload"])
    group = payload["materials"][0]
    parts = group["batch_allocations"]
    if problem == "sum": parts[1]["quantity"] = 199
    elif problem == "duplicate": parts[1]["stock_batch_id"] = parts[0]["stock_batch_id"]
    elif problem == "missing_anchor": group["stock_batch_id"] = 999999
    elif problem == "one_source": group["batch_allocations"] = parts[:1]
    elif problem == "zero": parts[0]["quantity"] = 0
    elif problem == "precision": parts[0]["quantity"] = 100.0001
    elif problem == "nan": parts[0]["quantity"] = "NaN"
    elif problem == "cross_group": payload["materials"].append({"stock_batch_id": parts[1]["stock_batch_id"], "planned_kg": 1})
    elif problem == "unassigned":
        with SessionLocal() as db:
            db.query(ProductionOrderMaterial).filter_by(production_order_id=case["order_id"], stock_batch_id=case["batches"][1]).delete(); db.commit()
    else:
        with SessionLocal() as db:
            batch = db.get(StockBatch, case["batches"][1])
            if problem == "color": batch.color = "blue"
            elif problem == "width": batch.width = 1.8
            elif problem == "gsm": batch.gsm = .2
            elif problem == "unit": batch.unit = "m"
            elif problem == "item": batch.item_id = 1 if batch.item_id != 1 else 2
            elif problem == "shortage": batch.quantity = 199
            db.commit()
    response = save(client, auth_headers, case, payload)
    assert response.status_code == status, response.text
    with SessionLocal() as db:
        assert db.query(CuttingPassport).filter_by(production_order_id=case["order_id"]).count() == 0
        assert db.query(StockMovement).filter(StockMovement.movement_type == "consume", StockMovement.batch_id.in_(case["batches"])).count() == 0


def test_used_group_is_readable_and_notes_save_but_allocations_calculations_are_locked(client, auth_headers, allocation_case):
    case = allocation_case
    saved = save(client, auth_headers, case).json()
    cut = confirm(client, auth_headers, case, saved)
    assert cut.status_code == 201, cut.text
    current = client.get(f"/api/cutting-passports/{saved['id']}", headers=auth_headers).json()
    current["notes"] = "QA saved note"
    assert client.put(f"/api/cutting-passports/{saved['id']}", headers=auth_headers, json=current).status_code == 200
    for field in ("allocations", "layers"):
        changed = deepcopy(current)
        if field == "allocations":
            changed["materials"][0]["batch_allocations"][0]["quantity"] = 99
            changed["materials"][0]["batch_allocations"][1]["quantity"] = 201
        else:
            changed["materials"][0]["layer_weight_kg"] = 2
            changed["materials"][0]["total_layers"] = 150
        response = client.put(f"/api/cutting-passports/{saved['id']}", headers=auth_headers, json=changed)
        assert response.status_code == 409, response.text
    url = f"/api/cutting/records/{cut.json()['id']}"
    assert client.patch(url, headers=auth_headers, json={"notes": "cutting note"}).status_code == 200
    assert client.patch(url, headers=auth_headers, json={"material_rolls_used": 9}).status_code == 409


def test_adding_second_batch_reuses_atomic_assignment_and_reservation(client, auth_headers, allocation_case):
    case = allocation_case
    with SessionLocal() as db:
        db.query(ProductionOrderMaterial).filter_by(production_order_id=case["order_id"], stock_batch_id=case["batches"][1]).delete()
        db.query(MaterialReservation).filter_by(production_order_id=case["order_id"], stock_batch_id=case["batches"][1]).delete()
        db.commit()
    payload = deepcopy(case["payload"])
    payload["additional_materials"] = [{"stock_batch_id": case["batches"][1], "estimated_quantity": 200, "unit": "kg"}]
    saved = save(client, auth_headers, case, payload)
    assert saved.status_code == 201, saved.text
    assert client.put(f"/api/cutting-passports/{saved.json()['id']}", headers=auth_headers, json=payload).status_code == 200
    with SessionLocal() as db:
        assert db.query(ProductionOrderMaterial).filter_by(production_order_id=case["order_id"]).count() == 2
        assert db.query(MaterialReservation).filter_by(production_order_id=case["order_id"], stock_batch_id=case["batches"][1]).count() == 1


def test_defaults_offer_own_reserved_stock_and_raw_dimensions(client, auth_headers, allocation_case):
    case = allocation_case
    response = client.get(f"/api/cutting-passports/material-defaults?production_order_id={case['order_id']}", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = response.json()["materials"]
    assert [row["available_quantity"] for row in rows] == [150, 250]
    assert all(row["unit"] == "kg" and row["color"] == "red" and row["width"] == 1.6 and row["gsm"] == .18 for row in rows)


def test_reversed_allocation_order_is_canonicalized_anchor_first(client, auth_headers, allocation_case):
    case = allocation_case
    payload = deepcopy(case["payload"])
    payload["materials"][0]["batch_allocations"].reverse()
    saved = save(client, auth_headers, case, payload)
    assert saved.status_code == 201, saved.text
    row = saved.json()["materials"][0]
    assert [part["stock_batch_id"] for part in row["batch_allocations"]] == case["batches"]
    assert row["lot_no"].startswith(row["batch_allocations"][0]["batch_no"])
    assert confirm(client, auth_headers, case, saved.json()).status_code == 201


def test_meter_group_preserves_authoritative_ties_even_rounding(client, auth_headers, allocation_case):
    case = allocation_case
    with SessionLocal() as db:
        for bid in case["batches"]: db.get(StockBatch, bid).unit = "m"
        for row in db.query(ProductionOrderMaterial).filter_by(production_order_id=case["order_id"]): row.unit = "m"
        db.commit()
    payload = deepcopy(case["payload"])
    row = payload["materials"][0]
    row.update(meter_mode=True, layer_weight_kg=1, total_layers=1, pieces=5, beka_per_piece_kg=.0001)
    row["batch_allocations"][0]["quantity"] = .333
    row["batch_allocations"][1]["quantity"] = .667
    result = save(client, auth_headers, case, payload)
    assert result.status_code == 201, result.text
    assert result.json()["materials"][0]["actual_kg"] == 1


def test_grouped_batch_replacement_preserves_split_and_consumes_new_source(client, auth_headers, allocation_case):
    case = allocation_case
    saved = save(client, auth_headers, case)
    assert saved.status_code == 201, saved.text
    replacement = _receive_batch(client, auth_headers, item_id=case["item"]["id"], warehouse_id=case["warehouse"]["id"], quantity=300, unit="kg")
    with SessionLocal() as db:
        batch = db.get(StockBatch, replacement["id"])
        batch.color = "red"; batch.width = 1.6; batch.gsm = .18
        db.commit()
    changed = client.patch(f"/api/work-orders/{case['work_id']}/cutting-materials/{case['batches'][1]}",
                           headers=auth_headers, json={"stock_batch_id": replacement["id"]})
    assert changed.status_code == 200, changed.text
    current = client.get(f"/api/cutting-passports/{saved.json()['id']}", headers=auth_headers).json()
    assert [part["stock_batch_id"] for part in current["materials"][0]["batch_allocations"]] == [case["batches"][0], replacement["id"]]
    cut = confirm(client, auth_headers, case, current)
    assert cut.status_code == 201, cut.text
    with SessionLocal() as db:
        assert db.get(StockBatch, case["batches"][1]).quantity == 250
        assert db.get(StockBatch, replacement["id"]).quantity == 100


def test_other_order_reservations_reduce_group_source_capacity(client, auth_headers, allocation_case):
    case = allocation_case
    with SessionLocal() as db:
        other = ProductionOrder(production_no="QA-OTHER-" + uuid4().hex[:8], production_type="branded_stock",
                                model_id=db.get(ProductionOrder, case["order_id"]).model_id, status="new", planned_quantity=1)
        db.add(other); db.flush()
        db.add(MaterialReservation(reservation_no="QA-OTHER-" + uuid4().hex[:8], production_order_id=other.id,
            item_id=case["item"]["id"], stock_batch_id=case["batches"][0], warehouse_id=case["warehouse"]["id"],
            reserved_quantity=80, consumed_quantity=0, released_quantity=0, unit="kg", source="manual",
            reservation_type="material", status="reserved"))
        db.commit()
    defaults = client.get(f"/api/cutting-passports/material-defaults?production_order_id={case['order_id']}", headers=auth_headers).json()
    assert defaults["materials"][0]["available_quantity"] == 70
    assert save(client, auth_headers, case).status_code == 409


@pytest.mark.parametrize("mode", ["raw_override", "omitted_passport", "deferred"])
def test_grouped_nastil_cannot_bypass_saved_usage_with_raw_or_deferred_payload(client, auth_headers, allocation_case, mode):
    case = allocation_case
    saved = save(client, auth_headers, case).json()
    payload = {"work_order_id": case["work_id"], "production_batch_id": saved["production_batch_id"],
               "input_quantity": 0, "cut_pieces": 600, "passed_pieces": 600, "use_passport_materials": False,
               "materials": [{"stock_batch_id": bid, "quantity": 100, "unit": "kg"} for bid in case["batches"]],
               "bundles": [{"color": "red", "size": "46", "quantity": 600, "count": 1, "next": "sewing", "sewing_factory": "milana"}]}
    if mode == "raw_override": payload["cutting_passport_id"] = saved["id"]
    if mode == "deferred": payload.update(defer_material_usage=True, materials=[])
    response = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    assert response.status_code == 409 and "grouped passport" in response.text, response.text
    with SessionLocal() as db:
        assert [float(db.get(StockBatch, bid).quantity) for bid in case["batches"]] == [150, 250]
        assert db.query(CuttingRecord).filter_by(work_order_id=case["work_id"]).count() == 0
        assert db.query(Bundle).filter_by(production_order_id=case["order_id"]).count() == 0


def test_known_other_factory_source_is_denied_without_expanding_legacy_warehouse_policy(client, auth_headers, allocation_case):
    case = allocation_case
    with SessionLocal() as db:
        department = db.query(Department).filter_by(code="ECO").one()
        warehouse = Warehouse(name="QA explicit ECO warehouse", type="fabric_storage", department_id=department.id)
        db.add(warehouse); db.flush()
        db.get(StockBatch, case["batches"][1]).warehouse_id = warehouse.id
        db.commit()
    assert save(client, auth_headers, case).status_code == 403


def test_source_metadata_is_linear_and_reversed_usages_render_the_same_single_calculation():
    from app.models.production.passport_material_allocation_service import allocated_usage_lines, material_sheet_entries
    count = 1000
    parts = [{"stock_batch_id": index, "quantity": 1, "batch_no": f"QA-{index}"} for index in range(1, count + 1)]
    source = {"stock_batch_id": 1, "batch_allocations": parts}
    common = {"layer_material_kg": 1, "beika_kg": .1, "material_rolls_used": 12,
              "cut_pieces": 600, "waste_quantity": .6, "waste_unit": "kg", "layup_operator_name": "QA"}
    lines = allocated_usage_lines(source, common, Decimal(count), "kg")
    assert sum(len(row["details"]["passport_material_group"].get("batch_allocations", [])) for row in lines) == count
    assert all(row["details"]["waste_quantity"] >= 0 for row in lines)
    assert sum(Decimal(str(row["details"]["waste_quantity"])) for row in lines) == Decimal(".6")
    stock = {part["stock_batch_id"]: SimpleNamespace(batch_no=part["batch_no"], item=SimpleNamespace(name="QA")) for part in parts}
    usages = [SimpleNamespace(**row, stock_batch=stock[row["stock_batch_id"]]) for row in lines]
    forward = material_sheet_entries(usages)
    reversed_rows = material_sheet_entries(reversed(usages))
    assert forward == reversed_rows
    assert len(forward) == 1 and forward[0]["quantity"] == 1000
    assert forward[0]["details"]["cut_pieces"] == 600 and forward[0]["details"]["material_rolls_used"] == 12
    assert "QA-1 (1 kg)" in forward[0]["lot_no"] and "QA-1000 (1 kg)" in forward[0]["lot_no"]

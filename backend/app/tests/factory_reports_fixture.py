"""Reusable isolated-browser facts. Caller owns its disposable DB and commit."""
from datetime import datetime, time, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.libs.dto.production.cutting_material import PassportMaterial
from app.schemas import (
    Bundle, BundleScanLog, CuttingPassport, CuttingRecord, Department, Item, Model,
    ModelSize, ProductionBatch, ProductionOrder, Shipment, StockBatch, User,
    Warehouse, WasteRecord, WorkOrder,
)


def uniform_invoice_document():
    return {
        "shipment_no": "QA-UNIFORM", "packages_count": 2, "quantity": 7, "amount": "17.50",
        "invoice_layout_version": 2,
        "package_details": [{"package_no": "QA-SHORT", "quantity": 3, "weight_kg": "1.25"},
                            {"package_no": "QA-LONG", "quantity": 4, "weight_kg": "1.50"}],
        "lines": [{"package_no": "QA-SHORT", "model_no": "QA-S", "description": "Short",
                   "size": "M", "quantity": 3, "unit_price": "2.50", "amount": "7.50"},
                  {"package_no": "QA-LONG", "model_no": "QA-L",
                   "description": "Long cotton garment description " * 8,
                   "size": "L", "quantity": 4, "unit_price": "2.50", "amount": "10.00"}],
    }


def build_factory_reports_fixture(db):
    marker = uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo("Asia/Tashkent")).date()
    calendar_stamp = datetime.combine(day, time.min, timezone.utc)
    depts = {row.code: row.id for row in db.query(Department)}
    for code in ("CUT", "ECT", "MIL", "ECO", "STR"):
        if code not in depts:
            row = Department(code=code, name=f"QA {code}")
            db.add(row)
            db.flush()
            depts[code] = row.id
    model = Model(code=f"QA-REPORT-{marker}", name="Factory report QA", status="approved")
    warehouse = Warehouse(name=f"QA report {marker}", type="fabric_storage", department_id=depts["STR"])
    db.add_all([model, warehouse])
    db.flush()
    db.add(ModelSize(model_id=model.id, size="M"))
    sources = []
    for unit in ("kg", "m"):
        item = Item(sku=f"QA-{marker}-{unit}", name=f"QA report fabric {unit}", category="fabric", unit=unit)
        db.add(item)
        db.flush()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=f"QA-{marker}-{unit}",
                           color="blue", quantity=1000, unit=unit, qc_status="passed")
        db.add(batch)
        db.flush()
        sources.append(batch.id)
    materials = [
        PassportMaterial(stock_batch_id=sources[0], fabric_type="QA cotton", lot_no="QA kg",
                         pieces=100, rolls_count=2, layer_weight_kg=2.5, total_layers=4,
                         planned_kg=15, scrap_kg=1, beka_per_piece_kg=.01, size_range="M").model_dump(),
        PassportMaterial(stock_batch_id=sources[1], fabric_type="QA woven", lot_no="QA m", meter_mode=True,
                         pieces=100, rolls_count=3, layer_weight_kg=3, total_layers=4,
                         planned_kg=16, scrap_kg=.5, beka_per_piece_kg=.02, size_range="M").model_dump(),
    ]
    result = {"marker": marker, "day": day.isoformat(), "factories": {}}
    for factory, department in (("MIL", "CUT"), ("ECO", "ECT")):
        actor = User(name=f"QA {factory} Cutting", email=f"qa-report-{factory}-{marker}@example.invalid",
                     password_hash="unused", factory_code=factory, is_active=True,
                     last_seen_at=now,
                     extra_permissions=["cutting.records", "cutting.bundles", "planning.production", "storage.shipment"])
        po = ProductionOrder(production_no=f"QA-{factory}-{marker}", production_type="branded_stock",
                             model_id=model.id, planned_quantity=100, status="cutting")
        db.add_all([actor, po])
        db.flush()
        wo = WorkOrder(production_order_id=po.id, department_id=depts[department],
                       operation="cutting", status="in_progress", planned_input_qty=100, planned_output_qty=100)
        passport = CuttingPassport(passport_no=f"QA-{factory}-{marker}", date=calendar_stamp,
                                   production_order_id=po.id, model_code=model.code, size_range="M", pieces=100,
                                   materials=materials, tepa_pass=factory == "MIL", operator_name_manual="QA operator")
        db.add_all([wo, passport])
        db.flush()
        batch = ProductionBatch(production_order_id=po.id, cutting_passport_id=passport.id,
                                batch_index=1, batch_no=f"QA-{factory}-{marker}-1", name="QA Nastil 1", planned_quantity=100)
        db.add(batch)
        db.flush()
        result["factories"][factory] = {"user_id": actor.id, "order_id": po.id, "work_order_id": wo.id,
                                          "passport_id": passport.id, "passport_no": passport.passport_no,
                                          "batch_id": batch.id,
                                          "expected_passports": {"passports": 1, "pieces": 400 if factory == "MIL" else 200,
                                                                 "fabric_kg": 12, "fabric_m": 14.5, "rolls": 5}}
    mixed = ProductionOrder(production_no=f"QA-MIXED-{marker}", production_type="branded_stock",
                            model_id=model.id, planned_quantity=57, status="cutting")
    db.add(mixed)
    db.flush()
    for factory, department, quantity in (("MIL", "CUT", 20), ("ECO", "ECT", 30)):
        wo = WorkOrder(production_order_id=mixed.id, department_id=depts[department], operation="cutting", status="in_progress")
        db.add(wo)
        db.flush()
        record = CuttingRecord(work_order_id=wo.id, cut_pieces=quantity, passed_pieces=quantity, approval_status="approved")
        db.add(record)
        db.flush()
        bundle = Bundle(production_order_id=mixed.id, model_id=model.id, cutting_record_id=record.id,
                        bundle_no=f"QA-{factory}-B-{marker}", barcode=f"QA-{factory}-B-{marker}",
                        color="blue", size="M", quantity=quantity, status="created", sewing_factory_code=factory,
                        next_department_id=depts[factory], created_at=now)
        db.add(bundle)
        db.flush()
        if factory == "MIL":
            sent = Bundle(production_order_id=mixed.id, model_id=model.id, cutting_record_id=record.id,
                          bundle_no=f"QA-SENT-{marker}", barcode=f"QA-SENT-{marker}", color="blue", size="M",
                          quantity=7, status="received_sewing", sewing_factory_code=factory,
                          next_department_id=depts[factory], created_at=now)
            db.add(sent)
            db.flush()
            db.add_all([BundleScanLog(bundle_id=sent.id, scan_type=kind, scanned_at=now)
                        for kind in ("received_printing", "received_printing", "received_sewing")])
            db.add_all([WasteRecord(source_department_id=depts[department], waste_type="cutting_waste",
                                    quantity=quantity, unit=unit, created_at=now)
                        for quantity, unit in ((2.5, "kg"), (3, "m"))])
        result["factories"][factory]["expected_board"] = {"bundles": 1, "pieces": quantity, "orders": 1, "work_orders": 1}
        result["factories"][factory]["bundle_id"] = bundle.id
    document = uniform_invoice_document()
    document["shipped_at"] = now.isoformat()
    shipment = Shipment(shipment_no=f"QA-INVOICE-{marker}", status="shipped", shipped_at=now,
                        dispatch_snapshot={"document": document})
    db.add(shipment)
    db.flush()
    result["shipment_id"] = shipment.id
    return result

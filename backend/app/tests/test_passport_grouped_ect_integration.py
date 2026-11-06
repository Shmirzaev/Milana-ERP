"""Combined grouped calculations and transferred ECT fabric; synthetic data only."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models.production.ect_passport_fabric_service import REVERSAL_REFERENCE
from app.schemas import (Bundle, CuttingMaterialUsage, CuttingPassport, CuttingRecord, Department,
                         ProductionOrderMaterial, StockBatch, StockMovement, User, Warehouse, WorkOrder)
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.tests.test_passport_batch_allocations import allocation_case, save, confirm  # noqa: F401


@pytest.fixture
def grouped_ect(allocation_case):
    case = allocation_case
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        db.get(WorkOrder, case["work_id"]).department_id = db.query(Department.id).filter_by(code="ECT").scalar()
        db.get(Warehouse, case["warehouse"]["id"]).department_id = db.query(Department.id).filter_by(code="CUT").scalar()
        receipts = []
        for source_id, amounts in zip(case["batches"], ((40, 60), (80, 120))):
            source = db.get(StockBatch, source_id)
            source.quantity = 0
            source.archived_at = datetime.now(timezone.utc)
            receipts.extend(EcoMaterialBatch(item_id=source.item_id, kind="fabric", batch_no=source.batch_no,
                color=source.color, unit=source.unit, quantity=amount, reserved_quantity=0,
                source_stock_batch_id=source.id, created_by=actor.id) for amount in amounts)
        db.add_all(receipts)
        db.commit()
        case["eco_ids"] = [row.id for row in receipts]
        case["headers"] = {"Authorization": f"Bearer {create_access_token(actor.id, extra={'factory_code': 'ECO'})}"}
    return case


def test_grouped_ect_100_plus_200_keeps_one_calculation_and_exact_physical_ledgers(client, grouped_ect):
    case = grouped_ect
    headers = case["headers"]
    defaults = client.get(f"/api/cutting-passports/material-defaults?production_order_id={case['order_id']}", headers=headers)
    assert defaults.status_code == 200, defaults.text
    assert [row["available_quantity"] for row in defaults.json()["materials"]] == [100, 200]
    assert all(row["warehouse_name"] == "Eco Cotton" for row in defaults.json()["materials"])
    created = save(client, headers, case)
    assert created.status_code == 201, created.text
    passport = created.json()
    assert len(passport["materials"]) == 1
    assert passport["actual_kg"] == passport["materials"][0]["actual_kg"] == 300
    assert passport["pieces"] == 600 and passport["rolls_count"] == 3
    dashboard = client.get("/api/cutting-passports/dashboard?date_from=2026-11-05&date_to=2026-11-05", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["totals"]["pieces"] == 600
    assert dashboard.json()["totals"]["fabric_kg"] == 300
    cut = confirm(client, headers, case, passport)
    assert cut.status_code == 201, cut.text
    assert [row["quantity"] for row in cut.json()["materials"]] == [100, 200]
    with SessionLocal() as db:
        assert [db.get(StockBatch, key).quantity for key in case["batches"]] == [0, 0]
        assert all(db.get(StockBatch, key).archived_at is not None for key in case["batches"])
        assert [db.get(EcoMaterialBatch, key).quantity for key in case["eco_ids"]] == [0, 0, 0, 0]
        assert db.query(StockMovement).filter_by(reference_type="CuttingRecord", reference_id=cut.json()["id"]).count() == 0
        assert db.query(EcoMaterialMovement).filter_by(reference_type="CuttingRecord", reference_id=cut.json()["id"]).count() == 4
        usages = db.query(CuttingMaterialUsage).filter_by(cutting_record_id=cut.json()["id"]).all()
        assert sum(row.details["cut_pieces"] for row in usages) == 600
        assert sum(row.details["material_rolls_used"] for row in usages) == 3
        assert sum(row.details["waste_quantity"] for row in usages) == 30
        assert db.query(Bundle).filter_by(production_order_id=case["order_id"]).one().quantity == 600
    reopened = client.get(f"/api/cutting-passports/{passport['id']}", headers=headers).json()
    edited = client.put(f"/api/cutting-passports/{passport['id']}", headers=headers, json={**reopened, "notes": "Grouped ECT note"})
    assert edited.status_code == 200, edited.text
    assert confirm(client, headers, case, passport).status_code == 409
    sheet = client.get(f"/api/cutting/records/{cut.json()['id']}/production-sheet", headers=headers)
    assert sheet.status_code == 200 and "300 kg" in sheet.text, sheet.text
    removed = client.delete(f"/api/work-orders/{case['work_id']}/batches/{passport['production_batch_id']}", headers=headers)
    assert removed.status_code == 200, removed.text
    with SessionLocal() as db:
        assert [db.get(StockBatch, key).quantity for key in case["batches"]] == [0, 0]
        assert [db.get(EcoMaterialBatch, key).quantity for key in case["eco_ids"]] == [40, 60, 80, 120]
        assert db.query(EcoMaterialMovement).filter_by(reference_type=REVERSAL_REFERENCE).count() == 4
        assert db.get(CuttingRecord, cut.json()["id"]) is None


@pytest.mark.parametrize("problem,status", [("shortage", 409), ("qc", 409), ("reserved", 409),
    ("unlinked", 409), ("color", 400), ("width", 400), ("gsm", 400), ("identity", 409), ("forged", 400)])
def test_grouped_ect_refuses_each_invalid_physical_source(client, grouped_ect, problem, status):
    case = grouped_ect
    payload = deepcopy(case["payload"])
    with SessionLocal() as db:
        source = db.get(StockBatch, case["batches"][1])
        first = db.get(EcoMaterialBatch, case["eco_ids"][0])
        if problem == "shortage":
            first.quantity = 39  # 99 on A, even if B has more than its 200 allocation.
            db.get(EcoMaterialBatch, case["eco_ids"][2]).quantity = 81
        elif problem == "qc": first.receipt_details = {"qc_status": "pending"}
        elif problem == "reserved": first.reserved_quantity = 1
        elif problem == "unlinked":
            for key in case["eco_ids"][2:]: db.get(EcoMaterialBatch, key).source_stock_batch_id = None
        elif problem == "color": source.color = "blue"
        elif problem == "width": source.width = 1.8
        elif problem == "gsm": source.gsm = .20
        elif problem == "identity": first.unit = "m"
        elif problem == "forged":
            extra = StockBatch(item_id=source.item_id, warehouse_id=source.warehouse_id, batch_no="UNASSIGNED",
                color="red", width=1.6, gsm=.18, unit="kg", quantity=500, qc_status="passed")
            db.add(extra); db.flush()
            db.add(EcoMaterialBatch(item_id=extra.item_id, kind="fabric", batch_no=extra.batch_no,
                color=extra.color, unit=extra.unit, quantity=500, reserved_quantity=0,
                source_stock_batch_id=extra.id, created_by=first.created_by))
            payload["materials"][0]["batch_allocations"][1]["stock_batch_id"] = extra.id
        db.commit()
    rejected = save(client, case["headers"], case, payload)
    assert rejected.status_code == status, rejected.text
    with SessionLocal() as db:
        assert db.query(CuttingPassport).filter_by(production_order_id=case["order_id"]).count() == 0
        assert db.query(EcoMaterialMovement).filter_by(reference_type="CuttingRecord").count() == 0
        assert [db.get(StockBatch, key).quantity for key in case["batches"]] == [0, 0]


def test_grouped_ect_wrong_factory_and_later_shortage_do_not_debit_other_sources(client, auth_headers, grouped_ect):
    case = grouped_ect
    assert save(client, auth_headers, case).status_code == 403
    saved = save(client, case["headers"], case)
    assert saved.status_code == 201, saved.text
    with SessionLocal() as db:
        db.get(EcoMaterialBatch, case["eco_ids"][2]).quantity = Decimal("79")
        db.commit()
    rejected = confirm(client, case["headers"], case, saved.json())
    assert rejected.status_code == 409, rejected.text
    with SessionLocal() as db:
        assert [db.get(EcoMaterialBatch, key).quantity for key in case["eco_ids"]] == [40, 60, 79, 120]
        assert db.query(EcoMaterialMovement).filter_by(reference_type="CuttingRecord").count() == 0
        assert db.query(CuttingRecord).filter_by(work_order_id=case["work_id"]).count() == 0


def test_grouped_ect_checks_the_planned_unit_of_every_physical_source(client, grouped_ect):
    case = grouped_ect
    saved = save(client, case["headers"], case)
    assert saved.status_code == 201, saved.text
    with SessionLocal() as db:
        db.query(ProductionOrderMaterial).filter_by(production_order_id=case["order_id"],
            stock_batch_id=case["batches"][1]).one().unit = "m"
        db.commit()
    rejected = confirm(client, case["headers"], case, saved.json())
    assert rejected.status_code == 400, rejected.text
    with SessionLocal() as db:
        assert [db.get(EcoMaterialBatch, key).quantity for key in case["eco_ids"]] == [40, 60, 80, 120]
        assert db.query(EcoMaterialMovement).filter_by(reference_type="CuttingRecord").count() == 0

"""Reusable isolated-only Planning -> ECO Cutting fixture (no production access)."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.core.security import create_access_token
from app.schemas import Brand, Department, Item, Model, ModelSize, Role, User, Warehouse
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement


def make_eco_fabric_case(sessions):
    marker = uuid4().hex[:10]
    with sessions() as db:
        departments = {row.code: row for row in db.query(Department)}
        for code in ("CUT", "ECT", "ECO", "ECP", "MIL", "PKG", "FGS", "PRT", "STR"):
            if code not in departments:
                row = Department(code=code, name=code)
                db.add(row); db.flush(); departments[code] = row
        roles = [Role(name=f"QA Planner {marker}", permissions=["planning.production"]),
                 Role(name=f"QA Operator {marker}", permissions=["*", "admin.super"])]
        db.add_all(roles); db.flush()
        actors = [User(name=f"QA {name} {marker}", email=f"{name}-{marker}@example.com", password_hash="unused",
                    factory_code="MIL", role_id=role.id, is_active=True, last_seen_at=datetime.now(timezone.utc))
                  for name, role in zip(("planner", "operator"), roles)]
        brand = Brand(name=f"QA ECO {marker}", is_active=True)
        item = Item(sku=f"QA-ECO-{marker}", name=f"QA direct ECO fabric {marker}", category="fabric", unit="kg")
        warehouse = Warehouse(name=f"QA ECO fabric {marker}", type="fabric_storage", department_id=departments["ECT"].id)
        db.add_all([*actors, brand, item, warehouse]); db.flush()
        model = Model(code=f"QA-ECO-{marker}", name=f"QA Eco Planning {marker}", status="approved", brand_id=brand.id,
                      catalog_scope="standard", factory_code="MIL")
        db.add(model); db.flush()
        db.add(ModelSize(model_id=model.id, size="46"))
        receipt = EcoMaterialBatch(item_id=item.id, kind="fabric", batch_no=f"ECO-DIRECT-{marker}", color="white",
            quantity=Decimal("100"), reserved_quantity=Decimal("10"), unit="kg", created_by=actors[1].id,
            receipt_details={"warehouse_id": warehouse.id, "qc_status": "passed", "width": "1.6", "gsm": ".18"})
        db.add(receipt); db.flush()
        db.add(EcoMaterialMovement(batch_id=receipt.id, kind="receive", quantity=100, created_by=actors[1].id))
        db.commit()
        return {"receipt": receipt.id, "batch_no": receipt.batch_no, "item": item.id, "model": model.id, "brand": brand.id,
            "planner": actors[0].id, "operator": actors[1].id,
            "mil_headers": {"Authorization": f"Bearer {create_access_token(actors[0].id, extra={'factory_code': 'MIL'})}"},
            "eco_headers": {"Authorization": f"Bearer {create_access_token(actors[1].id, extra={'factory_code': 'ECO'})}"}}


def planning_payload(case, **changes):
    return {"production_type": "branded_stock", "model_id": case["model"], "brand_id": case["brand"],
        "planned_quantity": 10, "cutting_department_code": "ECT", "sewing_factory_code": "ECO",
        "eco_fabric_batch_id": case["receipt"], "estimated_material_amount": 8,
        "materials": [{"eco_material_batch_id": case["receipt"], "estimated_quantity": 8, "unit": "kg"}],
        "items": [{"model_id": case["model"], "color": "white", "size": "46", "planned_quantity": 10}], **changes}

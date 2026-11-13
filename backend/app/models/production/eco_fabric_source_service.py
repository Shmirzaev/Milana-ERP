"""Resolve real ECO receipts to existing production material identities atomically.

Direct receipts have no Milana transfer source. An explicit order/passport save
may assign a zero-balance central identity, retaining the ECO receipt as the sole
physical ledger. GETs never create identities. The owning operation commits.
"""
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.deps import user_permissions
from app.libs.enums.production import CuttingDepartmentCode
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.inventory.eco_inventory_service import quality_passed
from app.models.identity.access_policy_service import denied_for
from app.schemas import Department, Item, StockBatch, User, Warehouse
from app.schemas.inventory.eco_fabric_identity import insert_direct_fabric_identity
from app.schemas.inventory.eco_inventory import EcoMaterialBatch


def require_eco_source_access(current: User, *, planning: bool) -> None:
    permissions = set(user_permissions(current))
    permission = "planning.production" if planning else "cutting.records"
    factories = {"MIL", "ECO"} if planning else {"ECO"}
    if (selected_factory_code(current) not in factories or not ({permission, "*"} & permissions)
            or (planning and "planning.production" in denied_for(current, "ECO"))):
        raise HTTPException(403, "Planning or Eco Cotton Cutting access is required for this fabric source")


def eco_fabric_options(db: Session, *, q: str = "", item_id: int | None = None) -> list[dict]:
    """Participating read projection; public callers authorize its narrow purpose."""
    query = db.query(EcoMaterialBatch, Item, StockBatch).join(Item, Item.id == EcoMaterialBatch.item_id).outerjoin(
        StockBatch, StockBatch.id == EcoMaterialBatch.source_stock_batch_id).filter(
            EcoMaterialBatch.kind == "fabric", Item.category.in_(("fabric", "semi_finished")), Item.is_active.is_(True))
    if item_id is not None:
        query = query.filter(Item.id == item_id)
    grouped = {}
    search = q.strip().casefold()
    for receipt, item, source in query.order_by(EcoMaterialBatch.id.desc()).all():
        if source and (source.item_id != receipt.item_id or source.unit != receipt.unit):
            continue
        details = receipt.receipt_details or {}
        key = ("central", source.id) if source else ("eco", receipt.id)
        row = grouped.setdefault(key, {"id": source.id if source else None,
            "eco_material_batch_id": None if source else receipt.id,
            "item_id": item.id, "item_name": item.name, "item_sku": item.sku, "item_category": item.category,
            "batch_no": source.batch_no if source else receipt.batch_no,
            "internal_batch_no": source.internal_batch_no if source else None,
            "color": source.color if source else receipt.color, "unit": receipt.unit, "width": source.width if source else details.get("width"),
            "gsm": source.gsm if source else details.get("gsm"), "image_url": details.get("image_url"),
            "warehouse_name": "Eco Cotton", "qc_status": "passed", "quantity": Decimal(0), "available_quantity": Decimal(0),
            "_search": set()})
        row["_search"].update(str(value or "").casefold() for value in (
            item.name, item.sku, receipt.batch_no, receipt.color,
            source.batch_no if source else None, source.internal_batch_no if source else None, source.color if source else None))
        row["quantity"] += Decimal(str(receipt.quantity))
        if quality_passed(receipt):
            row["available_quantity"] += Decimal(str(receipt.quantity)) - Decimal(str(receipt.reserved_quantity or 0))
    result = []
    for row in grouped.values():
        searchable = row.pop("_search")
        if row["available_quantity"] > 0 and (not search or any(search in value for value in searchable)):
            result.append({**row, "quantity": float(row["quantity"]), "available_quantity": float(row["available_quantity"])})
    return result


def list_planning_eco_fabrics(db: Session, current: User, q: str = "") -> list[dict]:
    # This is a narrow Planning source lookup, not ECO inventory access or a
    # factory session switch. General inventory and Cutting remain ECO-scoped.
    require_eco_source_access(current, planning=True)
    return eco_fabric_options(db, q=q)


def resolve_eco_fabric_sources(db: Session, rows: list[dict], current: User, *,
                             cutting_code: CuttingDepartmentCode, planning: bool) -> list[dict]:
    sources = [source for row in rows for source in [row, *(row.get("batch_allocations") or [])]]
    eco_ids = sorted({source["eco_material_batch_id"] for source in sources if source.get("eco_material_batch_id")})
    if not eco_ids:
        return [{key: ([{part_key: part_value for part_key, part_value in part.items() if part_key != "eco_material_batch_id"}
                         for part in value] if key == "batch_allocations" else value)
                 for key, value in row.items() if key != "eco_material_batch_id"} for row in rows]
    if cutting_code != CuttingDepartmentCode.ECO_COTTON:
        raise HTTPException(400, "Eco Cotton fabric requires Eco Cotton Cutting")
    require_eco_source_access(current, planning=planning)
    expected = dict(db.query(EcoMaterialBatch.id, EcoMaterialBatch.source_stock_batch_id).filter(
        EcoMaterialBatch.id.in_(eco_ids)).all())
    if len(expected) != len(eco_ids):
        raise HTTPException(404, "Eco Cotton fabric receipt not found")
    # Existing central identities always lock before receipts, matching actual
    # consumption. A newly linked receipt found after waiting is a safe conflict,
    # never a lock-order inversion or an attempted duplicate bridge insertion.
    central_ids = sorted({source["stock_batch_id"] for source in sources if source.get("stock_batch_id")} |
                         {value for value in expected.values() if value is not None})
    if central_ids:
        db.query(StockBatch.id).filter(StockBatch.id.in_(central_ids)).order_by(StockBatch.id).with_for_update().all()
    receipts = db.query(EcoMaterialBatch).filter(EcoMaterialBatch.id.in_(eco_ids)).order_by(
        EcoMaterialBatch.id).with_for_update(of=EcoMaterialBatch).populate_existing().all()
    mapping = {}
    for receipt in receipts:
        if receipt.source_stock_batch_id != expected[receipt.id]:
            raise HTTPException(409, "This fabric was just selected by another request. Reload and retry")
        item = db.get(Item, receipt.item_id)
        if receipt.kind != "fabric" or not item or not item.is_active or item.category not in {"fabric", "semi_finished"}:
            raise HTTPException(400, "Select an active Eco Cotton fabric receipt")
        if not quality_passed(receipt) or receipt.quantity <= receipt.reserved_quantity:
            raise HTTPException(409, "This Eco Cotton fabric is on hold, reserved or empty")
        if receipt.source_stock_batch_id is None:
            warehouse_id = (receipt.receipt_details or {}).get("warehouse_id")
            query = db.query(Warehouse).join(Department, Department.id == Warehouse.department_id).filter(
                Department.code.in_(("ECO", "ECT", "ECP")), Warehouse.type != "accessory_storage")
            warehouse = query.filter(Warehouse.id == warehouse_id).first() if warehouse_id else query.order_by(Warehouse.id).first()
            if warehouse is None:
                raise HTTPException(409, "Select an existing Eco Cotton fabric warehouse for this receipt")
            source = insert_direct_fabric_identity(db, receipt, warehouse_id=warehouse.id)
            log_action(db, current, "assign_cutting_identity", "EcoMaterialBatch", receipt.id,
                       new_value={"stock_batch_id": source.id, "central_quantity": 0})
        mapping[receipt.id] = receipt.source_stock_batch_id

    def resolved(source):
        result = {key: value for key, value in source.items() if key != "eco_material_batch_id"}
        if source.get("eco_material_batch_id"):
            result["stock_batch_id"] = mapping[source["eco_material_batch_id"]]
        if source.get("batch_allocations"):
            result["batch_allocations"] = [resolved(part) for part in source["batch_allocations"]]
        return result
    return [resolved(row) for row in rows]


def planning_eco_balances(db: Session, batch_ids: set[int], current: User,
                          cutting_code: CuttingDepartmentCode) -> dict[int, Decimal]:
    if not batch_ids:
        return {}
    receipts = db.query(EcoMaterialBatch).filter(EcoMaterialBatch.kind == "fabric",
        EcoMaterialBatch.source_stock_batch_id.in_(sorted(batch_ids))).order_by(EcoMaterialBatch.id).all()
    if not receipts:
        return {}
    if cutting_code != CuttingDepartmentCode.ECO_COTTON:
        raise HTTPException(400, "Eco Cotton fabric requires Eco Cotton Cutting")
    require_eco_source_access(current, planning=True)
    balances = {}
    for receipt in receipts:
        source = db.get(StockBatch, receipt.source_stock_batch_id)
        if source.item_id != receipt.item_id or source.unit != receipt.unit:
            raise HTTPException(409, "Eco Cotton fabric identity or unit has changed")
        balances.setdefault(source.id, Decimal(0))
        if quality_passed(receipt):
            balances[source.id] += Decimal(str(receipt.quantity)) - Decimal(str(receipt.reserved_quantity or 0))
    return balances

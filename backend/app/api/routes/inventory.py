from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Item, Warehouse, StockBatch, StockMovement, Supplier, User
from app.schemas.inventory import (
    ItemIn, ItemOut, WarehouseIn, WarehouseOut,
    StockBatchIn, StockBatchOut, StockMovementIn, StockMovementOut, StockLine,
)
from app.services.audit import log_action
from app.services.inventory import stock_summary, current_stock_for_item

router = APIRouter(prefix="/inventory", tags=["inventory"])


# ===== Items =====
@router.get("/items")
def list_items(
    db: DbSession,
    _: CurrentUser,
    category: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(Item).filter(Item.is_active.is_(True))
    if category: qry = qry.filter(Item.category == category)
    if q: qry = qry.filter((Item.name.ilike(f"%{q}%")) | (Item.sku.ilike(f"%{q}%")))
    total = qry.count() if include_total else 0
    qry = qry.order_by(Item.id.desc())
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.offset((safe_page - 1) * safe_size).limit(safe_size)
    rows = [ItemOut.model_validate(row).model_dump() for row in qry.all()]
    if include_total:
        return {"rows": rows, "total": total, "page": max(1, page), "page_size": max(1, min(page_size, 500))}
    return rows


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(payload: ItemIn, db: DbSession, current: User = Depends(require_permissions("storage.items", "*"))):
    if db.query(Item).filter(Item.sku == payload.sku).first():
        raise HTTPException(400, "SKU already exists")
    it = Item(**payload.model_dump())
    db.add(it); db.flush()
    log_action(db, current, "create", "Item", it.id, new_value={"sku": it.sku})
    db.commit(); db.refresh(it)
    return it


# ===== Warehouses =====
@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(db: DbSession, _: CurrentUser):
    return db.query(Warehouse).order_by(Warehouse.id).all()


@router.post("/warehouses", response_model=WarehouseOut, status_code=201)
def create_warehouse(payload: WarehouseIn, db: DbSession, current: User = Depends(require_permissions("admin.warehouses", "*"))):
    w = Warehouse(**payload.model_dump())
    db.add(w); db.flush()
    log_action(db, current, "create", "Warehouse", w.id)
    db.commit(); db.refresh(w)
    return w


# ===== Stock view =====
@router.get("/stock")
def get_stock(
    db: DbSession,
    _: CurrentUser,
    category: str | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    rows = stock_summary(db, category)
    total = len(rows)
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        rows = rows[(safe_page - 1) * safe_size : safe_page * safe_size]
    # adapt -> StockLine
    out = []
    for r in rows:
        out.append(StockLine(
            item_id=r["item_id"],
            item_sku=r["sku"],
            item_name=r["name"],
            warehouse_id=0,
            quantity=r["quantity"],
            unit=r["unit"],
        ).model_dump())
    if include_total:
        return {"rows": out, "total": total, "page": max(1, page), "page_size": max(1, min(page_size, 500))}
    return out


# ===== Receive (creates a batch + movement) =====
@router.post("/receive", response_model=StockBatchOut, status_code=201)
def receive_stock(payload: StockBatchIn, db: DbSession, current: User = Depends(require_permissions("storage.receive", "*"))):
    if not db.get(Item, payload.item_id):
        raise HTTPException(404, "Item not found")
    if not db.get(Warehouse, payload.warehouse_id):
        raise HTTPException(404, "Warehouse not found")
    batch = StockBatch(**payload.model_dump())
    db.add(batch); db.flush()
    mv = StockMovement(
        movement_type="receive",
        item_id=payload.item_id,
        batch_id=batch.id,
        to_warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        unit=payload.unit,
        reference_type="StockBatch",
        reference_id=batch.id,
        created_by=current.id,
    )
    db.add(mv)
    log_action(db, current, "receive", "StockBatch", batch.id, new_value={"batch_no": batch.batch_no, "qty": float(batch.quantity)})
    db.commit(); db.refresh(batch)
    return batch


# ===== Transfer =====
@router.post("/transfer", response_model=StockMovementOut, status_code=201)
def transfer_stock(payload: StockMovementIn, db: DbSession, current: User = Depends(require_permissions("storage.transfer", "*"))):
    if payload.movement_type not in ("transfer", "issue", "consume", "adjustment", "return"):
        raise HTTPException(400, "Invalid movement_type")
    mv = StockMovement(**payload.model_dump(), created_by=current.id)
    db.add(mv); db.flush()
    log_action(db, current, payload.movement_type, "StockMovement", mv.id)
    db.commit(); db.refresh(mv)
    return mv


# ===== Batches =====
@router.get("/batches")
def list_batches(
    db: DbSession,
    _: CurrentUser,
    item_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    qry = (
        db.query(StockBatch, Item, Warehouse, Supplier)
        .join(Item, Item.id == StockBatch.item_id)
        .join(Warehouse, Warehouse.id == StockBatch.warehouse_id)
        .outerjoin(Supplier, Supplier.id == StockBatch.supplier_id)
    )
    if item_id:
        qry = qry.filter(StockBatch.item_id == item_id)
    total = qry.count() if include_total else 0
    qry = qry.order_by(StockBatch.id.desc())
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.offset((safe_page - 1) * safe_size).limit(safe_size)
    rows = qry.all()
    out = [
        {
            **StockBatchOut.model_validate(batch).model_dump(),
            "item_sku": item.sku if item else None,
            "item_name": item.name if item else None,
            "supplier_name": supplier.name if supplier else None,
            "warehouse_name": warehouse.name if warehouse else None,
        }
        for batch, item, warehouse, supplier in rows
    ]
    if include_total:
        return {"rows": out, "total": total, "page": max(1, page), "page_size": max(1, min(page_size, 500))}
    return out

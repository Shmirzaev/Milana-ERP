from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, UploadFile, File, Response, Query

from app.core.dt import date_filter_bounds
from app.core.deps import (
    DbSession,
    INVENTORY_READ_PERMISSIONS,
    WAREHOUSE_READ_PERMISSIONS,
    PRODUCTION_READ_PERMISSIONS,
    require_permissions,
)
from app.schemas import User
from app.libs.dto.inventory.accessory_issue_input import AccessoryIssueIn
from app.libs.dto.inventory.accessory_issue_output import (
    AccessoryIssueOut, AccessoryIssuePlanOut,
)
from app.libs.dto.inventory.accessory_return_input import AccessoryReturnIn
from app.libs.dto.inventory.item_image_input import ItemImageIn
from app.libs.dto.inventory.item_input import ItemIn
from app.libs.dto.inventory.item_output import ItemOut
from app.libs.dto.inventory.material_reservation_input import (
    MaterialReservationAutoIn, MaterialReservationConsumeIn, MaterialReservationIn,
)
from app.libs.dto.inventory.material_reservation_output import (
    MaterialReservationOut, MaterialReservationPlanOut,
)
from app.libs.dto.inventory.stock_batch_input import StockBatchIn
from app.libs.dto.inventory.stock_batch_output import StockBatchOut
from app.libs.dto.inventory.stock_batch_restore_input import StockBatchRestoreIn
from app.libs.dto.inventory.stock_batch_roll_weights_input import StockBatchRollWeightsIn
from app.libs.dto.inventory.stock_batch_update import StockBatchUpdate
from app.libs.dto.inventory.stock_movement_input import StockMovementIn
from app.libs.dto.inventory.stock_movement_output import StockMovementOut
from app.libs.dto.inventory.stock_quantity_adjustment_input import StockQuantityAdjustmentIn
from app.libs.dto.inventory.stock_quantity_adjustment_output import StockQuantityAdjustmentOut
from app.libs.dto.inventory.warehouse_input import WarehouseIn
from app.libs.dto.inventory.warehouse_output import WarehouseCreatedOut, WarehouseOut
from app.models.inventory import reservations_service
from app.models.inventory import stock_service
from app.models.inventory import transfers_service
from app.models.inventory_reports_service import (
    ReportLanguage,
    build_material_inventory_pdf,
    build_material_inventory_xlsx,
    material_inventory_report_rows,
)
from app.models.cutting_fabric_usage_service import cutting_fabric_usage
from app.core.config import settings

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/cutting-fabric-usage")
def get_cutting_fabric_usage(
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "storage.receive", "cutting.records", "planning.production", "*")),
    q: str | None = Query(None, max_length=200),
    date_from: date | None = None,
    date_to: date | None = None,
    item_id: int | None = Query(None, ge=1),
    batch_id: int | None = Query(None, ge=1),
    unit: str | None = Query(None, max_length=32),
    cutting_department: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    return cutting_fabric_usage(
        db, current, q=q, date_from=date_from, date_to=date_to,
        item_id=item_id, batch_id=batch_id, unit=unit,
        cutting_department=cutting_department, page=page, page_size=page_size,
    )


def _material_report_timestamp() -> tuple[str, str]:
    timestamp = datetime.now(ZoneInfo("Asia/Tashkent"))
    return timestamp.strftime("%Y-%m-%d %H:%M"), timestamp.strftime("%Y%m%d_%H%M")


@router.get("/reports/material-stock.xlsx")
def download_material_stock_excel(
    db: DbSession,
    lang: ReportLanguage = "uz",
    supplier_id: int | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
):
    generated_label, filename_timestamp = _material_report_timestamp()
    start, end = date_filter_bounds(created_from, created_to)
    content = build_material_inventory_xlsx(
        material_inventory_report_rows(
            db,
            supplier_id=supplier_id,
            created_from=start,
            created_to=end,
        ),
        generated_label,
        lang,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="material_inventory_report_{filename_timestamp}.xlsx"'
            ),
        },
    )


@router.get("/reports/material-stock.pdf")
def download_material_stock_pdf(
    db: DbSession,
    lang: ReportLanguage = "uz",
    supplier_id: int | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
):
    generated_label, filename_timestamp = _material_report_timestamp()
    start, end = date_filter_bounds(created_from, created_to)
    content = build_material_inventory_pdf(
        material_inventory_report_rows(
            db,
            supplier_id=supplier_id,
            created_from=start,
            created_to=end,
        ),
        generated_label,
        lang,
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="material_inventory_report_{filename_timestamp}.pdf"'
            ),
        },
    )


# ===== Items =====
@router.get("/items")
def list_items(
    db: DbSession,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    return stock_service.list_items(
        db, _, category=category, group=group, q=q, created_from=created_from,
        created_to=created_to, page=page, page_size=page_size, include_total=include_total,
    )


@router.post("/items/image/upload", status_code=201)
async def upload_item_image(
    file: UploadFile = File(...),
    _: User = Depends(require_permissions("storage.items", "storage.receive", "*")),
):
    from app.models.image_storage_service import store_uploaded_image

    stored = await store_uploaded_image(
        file,
        target_dir=settings.MODEL_FILES_DIR,
        file_url_base="/storage/model-files",
        name_prefix="item",
        max_bytes=10 * 1024 * 1024,
        prebuild_thumbnails=True,
    )
    return {"file_url": stored.file_url}


@router.patch("/items/{item_id}/image", response_model=ItemOut)
def update_item_image(
    item_id: int,
    payload: ItemImageIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "storage.receive", "*")),
):
    return stock_service.update_item_image(db, item_id, payload, current)


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(payload: ItemIn, db: DbSession, current: User = Depends(require_permissions("storage.items", "*"))):
    return stock_service.create_item(db, payload, current)


@router.patch("/items/{item_id}", response_model=ItemOut)
def update_item(
    item_id: int,
    payload: ItemIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "*")),
):
    return stock_service.update_item(db, item_id, payload, current)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "*")),
    force: bool = False,
):
    archived = stock_service.delete_item(db, item_id, current, force=force)
    if archived:
        return Response(status_code=204)


# ===== Warehouses =====
@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(db: DbSession, _: User = Depends(require_permissions(*WAREHOUSE_READ_PERMISSIONS))):
    return stock_service.list_warehouses(db, _)


@router.post("/warehouses", response_model=WarehouseCreatedOut, status_code=201)
def create_warehouse(payload: WarehouseIn, db: DbSession, current: User = Depends(require_permissions("admin.warehouses", "*"))):
    return stock_service.create_warehouse(db, payload, current)


# ===== Stock view =====
@router.get("/stock")
def get_stock(
    db: DbSession,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    supplier_id: int | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    return stock_service.stock_view(
        db, _, category=category, group=group, q=q, supplier_id=supplier_id,
        created_from=created_from, created_to=created_to, page=page,
        page_size=page_size, include_total=include_total,
    )


@router.patch("/stock/{item_id}", response_model=StockQuantityAdjustmentOut)
def set_stock_quantity(
    item_id: int,
    payload: StockQuantityAdjustmentIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "storage.receive", "storage.transfer", "*")),
    force: bool = False,
):
    return stock_service.set_stock_quantity(db, item_id, payload, current, force=force)


# ===== Receive (creates a batch + movement) =====
@router.get("/colors", response_model=list[str])
def list_received_stock_colors(
    db: DbSession,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
):
    return stock_service.list_received_stock_colors(db, _)


@router.post("/receive", response_model=StockBatchOut, status_code=201)
def receive_stock(
    payload: StockBatchIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.receive", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StockBatchOut:
    return stock_service.receive_stock(db, payload, current, idempotency_key=idempotency_key)


# ===== Accessory issues to production =====
@router.post("/accessory-returns", response_model=StockBatchOut, status_code=201)
def collect_back_accessory(
    payload: AccessoryReturnIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.receive", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return stock_service.collect_back_accessory(db, payload, current, idempotency_key=idempotency_key)


@router.get("/accessory-issue-plan", response_model=AccessoryIssuePlanOut)
def get_accessory_issue_plan(
    production_order_id: int,
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
):
    return stock_service.accessory_issue_plan_view(db, _, production_order_id)


@router.get("/accessory-issues")
def list_accessory_issues(
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    return stock_service.list_accessory_issue_summary(
        db, _, production_order_id=production_order_id, model_id=model_id, q=q,
        page=page, page_size=page_size, include_total=include_total,
    )


@router.get("/accessory-issue-requests")
def list_accessory_issue_requests(
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    include_complete: bool = False,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    return stock_service.list_accessory_issue_request_rows(
        db, _, production_order_id=production_order_id, model_id=model_id, q=q,
        include_complete=include_complete, page=page, page_size=page_size,
        include_total=include_total,
    )


@router.post("/accessory-issues", response_model=AccessoryIssueOut, status_code=201)
def issue_accessories(
    payload: AccessoryIssueIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.transfer", "*")),
):
    return stock_service.issue_accessories(db, payload, current)


# ===== Material reservations =====
@router.get("/reservations", response_model=list[MaterialReservationOut])
def list_material_reservations(
    db: DbSession,
    _: User = Depends(require_permissions("inventory.reservations.view", "*")),
    production_order_id: int | None = None,
    sales_order_id: int | None = None,
    item_id: int | None = None,
    status: str | None = None,
):
    return reservations_service.list_material_reservations(
        db, _, production_order_id=production_order_id, sales_order_id=sales_order_id,
        item_id=item_id, status=status,
    )


@router.get("/reservations/plan", response_model=MaterialReservationPlanOut)
def get_material_reservation_plan(
    production_order_id: int,
    db: DbSession,
    _: User = Depends(require_permissions("inventory.reservations.view", "planning.reserve_materials", "*")),
):
    return reservations_service.material_reservation_plan(db, _, production_order_id)


@router.post("/reservations", response_model=MaterialReservationOut, status_code=201)
def create_material_reservation(
    payload: MaterialReservationIn,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.reservations.create", "planning.reserve_materials", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return reservations_service.create_material_reservation(
        db, payload, current, idempotency_key=idempotency_key,
    )


@router.post("/reservations/auto", status_code=201)
def auto_create_material_reservations(
    payload: MaterialReservationAutoIn,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.reservations.create", "planning.reserve_materials", "*")),
):
    return reservations_service.auto_create_material_reservations(db, payload, current)


@router.post("/reservations/{reservation_id}/release", response_model=MaterialReservationOut)
def release_reservation(
    reservation_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.reservations.release", "*")),
):
    return reservations_service.release_material_reservation(db, reservation_id, current)


@router.post("/reservations/{reservation_id}/consume", response_model=MaterialReservationOut)
def consume_reservation(
    reservation_id: int,
    payload: MaterialReservationConsumeIn,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.reservations.consume", "*")),
):
    return reservations_service.consume_material_reservation(db, reservation_id, payload, current)


# ===== Transfer =====
@router.post("/transfer", response_model=StockMovementOut, status_code=201)
def transfer_stock(
    payload: StockMovementIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.transfer", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return transfers_service.transfer_stock(db, payload, current, idempotency_key=idempotency_key)


# ===== Batches =====
@router.put("/batches/{batch_id}/roll-weights", response_model=StockBatchOut)
def save_batch_roll_weights(
    batch_id: int,
    payload: StockBatchRollWeightsIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "storage.receive", "*")),
):
    return stock_service.save_batch_roll_weights(db, batch_id, payload, current)


@router.patch("/batches/{batch_id}", response_model=StockBatchOut)
def update_batch(
    batch_id: int,
    payload: StockBatchUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "storage.receive", "*")),
    force: bool = False,
):
    return stock_service.update_batch(db, batch_id, payload, current, force=force)


@router.delete("/batches/{batch_id}", status_code=204)
def archive_or_delete_batch(
    batch_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.batches.delete", "*")),
    force: bool = False,
):
    stock_service.archive_or_delete_batch(db, batch_id, current, force=force)


@router.post("/batches/{batch_id}/restore", response_model=StockBatchOut)
def restore_material_batch(
    batch_id: int,
    payload: StockBatchRestoreIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.receive", "*")),
):
    return stock_service.restore_material_batch(db, batch_id, payload, current)


@router.get("/batches")
def list_batches(
    db: DbSession,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
    item_id: int | None = None,
    item_ids: str | None = None,
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    supplier_id: int | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
    hide_empty: bool = False,
    archived: bool = False,
):
    return stock_service.list_batches(
        db, _, item_id=item_id, item_ids=item_ids, category=category, group=group, q=q,
        supplier_id=supplier_id, created_from=created_from, created_to=created_to,
        page=page, page_size=page_size, include_total=include_total,
        hide_empty=hide_empty, archived=archived,
    )

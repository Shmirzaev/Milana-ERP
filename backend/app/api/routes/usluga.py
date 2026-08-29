from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import selectinload

from app.api.routes import catalog as catalog_routes
from app.core.deps import DbSession, require_permissions
from app.models import (
    Bundle,
    CuttingRecord,
    FinishedGoodsStock,
    Model,
    Package,
    PackageScanLog,
    PackagingReceipt,
    PackagingRecord,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    SewingAssignment,
    SewingRecord,
    User,
    WorkOrder,
)
from app.services.audit import log_action
from app.services.factory_scope import require_factory_access
from app.services.production import create_production_order, create_work_orders
from app.schemas.catalog import (
    ModelBOMIn,
    ModelBOMUpdate,
    ModelDetail,
    ModelImageIn,
    ModelIn,
    ModelOptionPage,
    ModelOut,
    ModelPaidOperationsIn,
    ModelSizeIn,
    ModelColorIn,
    ModelVariantCreateIn,
    ModelVariantUpdateIn,
)


router = APIRouter(prefix="/usluga", tags=["usluga"])


def _require_eco(current: User) -> None:
    require_factory_access(current, "ECO")


def _clean(value: str | None) -> str | None:
    return str(value or "").strip() or None


class UslugaSizeLineIn(BaseModel):
    size: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0, le=1_000_000)

    @field_validator("size")
    @classmethod
    def strip_size(cls, value: str) -> str:
        return value.strip()


class UslugaPlanLineIn(UslugaSizeLineIn):
    color: str = Field(min_length=1, max_length=64)

    @field_validator("color")
    @classmethod
    def strip_color(cls, value: str) -> str:
        return value.strip()


class UslugaOrderIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    customer_name: str = Field(min_length=1, max_length=255)
    customer_reference: str | None = Field(default=None, max_length=128)
    model_id: int = Field(gt=0)
    color: str | None = Field(default=None, max_length=64)
    sizes: list[UslugaSizeLineIn] = Field(default_factory=list, max_length=100)
    lines: list[UslugaPlanLineIn] = Field(default_factory=list, max_length=200)
    deadline: datetime | None = None
    material_description: str | None = None
    material_usage_kg: float | None = Field(default=None, ge=0, le=1_000_000)
    material_notes: str | None = None
    notes: str | None = None

    @field_validator("customer_name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_plan_lines(self):
        if self.lines:
            return self
        if self.sizes and str(self.color or "").strip():
            self.color = str(self.color).strip()
            return self
        raise ValueError("Enter at least one color/size quantity line")


class UslugaMaterialIn(BaseModel):
    material_usage_kg: float = Field(ge=0, le=1_000_000)
    material_description: str | None = None
    material_notes: str | None = None


class UslugaOrderUpdateIn(UslugaOrderIn):
    pass


class UslugaHandoverIn(BaseModel):
    recipient: str = Field(min_length=1, max_length=255)
    notes: str | None = None

    @field_validator("recipient")
    @classmethod
    def strip_recipient(cls, value: str) -> str:
        return value.strip()


def _model_payload(model: Model) -> dict:
    primary = next((row for row in model.images if row.is_primary), None) or (model.images[0] if model.images else None)
    return {
        "id": model.id,
        "code": model.code,
        "name": model.name,
        "category": model.category,
        "description": model.description,
        "image_url": primary.file_url if primary else None,
        "sizes": [row.size for row in sorted(model.sizes, key=lambda row: row.id)],
        "colors": [row.color_name for row in sorted(model.colors, key=lambda row: row.id)],
        "created_at": model.created_at,
    }


def _usluga_model_query(db: DbSession):
    return (
        db.query(Model)
        .options(selectinload(Model.images), selectinload(Model.sizes), selectinload(Model.colors))
        .filter(Model.catalog_scope == "usluga", Model.factory_code == "ECO")
    )


def _require_usluga_order(db: DbSession, order_id: int) -> ProductionOrder:
    order = db.query(ProductionOrder).filter(
        ProductionOrder.id == order_id,
        ProductionOrder.source_type == "usluga",
    ).one_or_none()
    if not order:
        raise HTTPException(404, "Usluga order not found")
    return order


def _normalized_plan_lines(payload: UslugaOrderIn, model: Model) -> list[UslugaPlanLineIn]:
    allowed_sizes = {row.size for row in model.sizes}
    plan_lines = payload.lines or [
        UslugaPlanLineIn(color=str(payload.color or "").strip(), size=row.size, quantity=row.quantity)
        for row in payload.sizes
    ]
    line_keys = {(row.color.casefold(), row.size.casefold()) for row in plan_lines}
    if len(line_keys) != len(plan_lines):
        raise HTTPException(400, "Duplicate color and size rows are not allowed")
    unknown_sizes = sorted({row.size for row in plan_lines} - allowed_sizes)
    if unknown_sizes:
        raise HTTPException(400, f"Sizes are not configured on this Usluga model: {', '.join(unknown_sizes)}")
    return plan_lines


def _plan_signature(model_id: int, rows: list[ProductionOrderItem] | list[UslugaPlanLineIn]) -> tuple:
    normalized = []
    for row in rows:
        quantity = int(row.planned_quantity if isinstance(row, ProductionOrderItem) else row.quantity)
        normalized.append((str(row.color).strip(), str(row.size).strip(), quantity))
    return int(model_id), tuple(sorted(normalized, key=lambda value: (value[0].casefold(), value[1].casefold())))


def _structural_edit_blocker(db: DbSession, order: ProductionOrder) -> str | None:
    if db.query(ProductionBatch.id).filter(ProductionBatch.production_order_id == order.id).first():
        return "Production batches already exist"
    if db.query(Bundle.id).filter(Bundle.production_order_id == order.id).first():
        return "Cut bundles already exist"
    if db.query(Package.id).filter(Package.production_order_id == order.id).first():
        return "Packages already exist"

    work_orders = db.query(WorkOrder).filter(WorkOrder.production_order_id == order.id).all()
    work_order_ids = [int(row.id) for row in work_orders]
    if any(
        int(row.actual_input_qty or 0) > 0
        or int(row.actual_output_qty or 0) > 0
        or int(row.passed_qty or 0) > 0
        or int(row.failed_qty or 0) > 0
        or int(row.rework_qty or 0) > 0
        or row.end_time is not None
        or row.status in {"completed", "rejected"}
        for row in work_orders
    ):
        return "Production quantities have already been recorded"
    if db.query(ProductionOrderItem.id).filter(
        ProductionOrderItem.production_order_id == order.id,
        ProductionOrderItem.completed_quantity > 0,
    ).first():
        return "Completed size quantities already exist"
    if not work_order_ids:
        return None
    for record_model, label in (
        (CuttingRecord, "Cutting records already exist"),
        (SewingRecord, "Sewing records already exist"),
        (PackagingRecord, "Packaging records already exist"),
        (PackagingReceipt, "Packaging receipts already exist"),
        (SewingAssignment, "Sewing assignments already exist"),
    ):
        if db.query(record_model.id).filter(record_model.work_order_id.in_(work_order_ids)).first():
            return label
    return None


def _order_payload(db: DbSession, order: ProductionOrder) -> dict:
    model = _usluga_model_query(db).filter(Model.id == order.model_id).one_or_none()
    work_orders = (
        db.query(WorkOrder)
        .filter(WorkOrder.production_order_id == order.id)
        .order_by(WorkOrder.id)
        .all()
    )
    packages = db.query(Package).filter(Package.production_order_id == order.id).order_by(Package.id).all()
    by_operation = {row.operation: row for row in work_orders}
    packaging = by_operation.get("packaging")
    required_operations_complete = all(
        by_operation.get(operation) is not None and by_operation[operation].status == "completed"
        for operation in ("cutting", "sewing", "packaging")
    )
    package_total = sum(int(row.total_quantity or 0) for row in packages)
    packed_total = int(packaging.passed_qty or 0) if packaging else 0
    return {
        "id": order.id,
        "order_no": order.production_no,
        "status": order.status,
        "customer_name": order.service_customer_name,
        "customer_reference": order.service_customer_reference,
        "model": _model_payload(model) if model else None,
        "model_id": order.model_id,
        "planned_quantity": order.planned_quantity,
        "deadline": order.deadline,
        "material_description": order.service_material_description,
        "material_usage_kg": float(order.service_material_usage_kg) if order.service_material_usage_kg is not None else None,
        "material_notes": order.service_material_notes,
        "handover_recipient": order.service_handover_recipient,
        "handover_notes": order.service_handover_notes,
        "handed_over_at": order.handed_over_at,
        "created_at": order.created_at,
        "items": [
            {"id": row.id, "color": row.color, "size": row.size, "planned_quantity": row.planned_quantity}
            for row in sorted(order.items, key=lambda row: row.id)
        ],
        "work_orders": [
            {
                "id": row.id,
                "operation": row.operation,
                "status": row.status,
                "planned_quantity": row.planned_output_qty,
                "passed_quantity": row.passed_qty,
                "failed_quantity": row.failed_qty,
            }
            for row in work_orders
        ],
        "package_count": len(packages),
        "package_quantity": package_total,
        "packed_quantity": packed_total,
        "ready_for_handover": bool(
            required_operations_complete
            and packaging
            and packed_total > 0
            and package_total >= packed_total
            and order.handed_over_at is None
        ),
    }


def _usluga_viewer(current: User) -> User:
    _require_eco(current)
    return current


@router.get("/model-options", response_model=ModelOptionPage)
def list_usluga_model_options(
    db: DbSession,
    current: User = Depends(require_permissions("usluga.view", "usluga.manage", "*")),
    status: str | None = Query(default=None, max_length=32),
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=50),
    ids: list[int] | None = Query(default=None),
):
    _usluga_viewer(current)
    return catalog_routes.list_model_options(db, current, status, search, page, page_size, ids, "usluga")


@router.get("/models")
def list_usluga_models(
    db: DbSession,
    response: Response,
    current: User = Depends(require_permissions("usluga.view", "usluga.manage", "*")),
    status: str | None = None,
    q: str | None = None,
    code: str | None = None,
    name: str | None = None,
    category: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_total: bool = False,
    include_legacy_import: bool = False,
):
    _usluga_viewer(current)
    return catalog_routes.list_models(
        db, current, response, status, q, code, name, category, created_from, created_to,
        page, page_size, include_total, include_legacy_import, "usluga",
    )


@router.get("/models/variant-groups")
def list_usluga_model_variant_groups(
    db: DbSession,
    current: User = Depends(require_permissions("usluga.view", "usluga.manage", "*")),
    status: str | None = None,
    q: str | None = None,
    code: str | None = None,
    name: str | None = None,
    category: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
    include_legacy_import: bool = False,
    compact: bool = False,
):
    _usluga_viewer(current)
    return catalog_routes.list_model_variant_groups(
        db, current, status, q, code, name, category, created_from, created_to,
        page, page_size, include_total, include_legacy_import, compact, "usluga",
    )


@router.get("/models/bom-items")
def list_usluga_model_bom_items(
    db: DbSession,
    current: User = Depends(require_permissions("usluga.view", "usluga.manage", "*")),
):
    _usluga_viewer(current)
    return catalog_routes.list_model_bom_items(db, current)


@router.post("/models", response_model=ModelOut, status_code=201)
def create_usluga_model(
    payload: ModelIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.create_model(payload, db, current, "usluga")


@router.get("/models/{mid}", response_model=ModelDetail)
def get_usluga_model(
    mid: int,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.view", "usluga.manage", "*")),
):
    _usluga_viewer(current)
    return catalog_routes.get_model(mid, db, current, "usluga")


@router.post("/models/{mid}/clone", response_model=ModelOut, status_code=201)
def clone_usluga_model(mid: int, db: DbSession, current: User = Depends(require_permissions("usluga.manage", "*"))):
    _require_eco(current)
    return catalog_routes.clone_model(mid, db, current, "usluga")


@router.get("/models/{mid}/variants")
def list_usluga_model_variants(
    mid: int,
    response: Response,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.view", "usluga.manage", "*")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
):
    _usluga_viewer(current)
    return catalog_routes.list_model_variants(mid, response, db, current, page, page_size, "usluga")


@router.get("/models/{mid}/variants/next-number")
def next_usluga_model_variant(mid: int, db: DbSession, current: User = Depends(require_permissions("usluga.manage", "*"))):
    _require_eco(current)
    return catalog_routes.get_next_model_variant_number(mid, db, current, "usluga")


@router.post("/models/{mid}/variants", response_model=ModelOut, status_code=201)
def create_usluga_model_variant(
    mid: int,
    payload: ModelVariantCreateIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.create_model_variant(mid, payload, db, current, "usluga")


@router.patch("/models/{mid}/variants/{variant_id}", response_model=ModelOut)
def update_usluga_model_variant(
    mid: int,
    variant_id: int,
    payload: ModelVariantUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.update_model_variant(mid, variant_id, payload, db, current, "usluga")


@router.delete("/models/{mid}/variants/{variant_id}", status_code=204)
def delete_usluga_model_variant(
    mid: int,
    variant_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.delete_model_variant(mid, variant_id, db, current, "usluga")


@router.patch("/models/{mid}", response_model=ModelOut)
def update_usluga_model(
    mid: int,
    payload: ModelIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.update_model(mid, payload, db, current, "usluga")


@router.patch("/models/{mid}/paid-operations", response_model=ModelOut)
def update_usluga_paid_operations(
    mid: int,
    payload: ModelPaidOperationsIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.update_model_paid_operations(mid, payload, db, current, "usluga")


@router.post("/models/{mid}/approve", response_model=ModelOut)
def approve_usluga_model(mid: int, db: DbSession, current: User = Depends(require_permissions("usluga.manage", "*"))):
    _require_eco(current)
    return catalog_routes.approve_model(mid, db, current, "usluga")


@router.post("/models/{mid}/images", status_code=201)
def add_usluga_model_image(
    mid: int,
    payload: ModelImageIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.add_image(mid, payload, db, current, "usluga")


@router.post("/models/{mid}/images/upload", status_code=201)
async def upload_usluga_model_image(
    mid: int,
    db: DbSession,
    file: UploadFile = File(...),
    image_type: str | None = Form(None),
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return await catalog_routes.upload_image(mid, db, file, image_type, current, "usluga")


@router.delete("/models/{mid}/images/{image_id}", status_code=204)
def delete_usluga_model_image(
    mid: int,
    image_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.delete_image(mid, image_id, db, current, "usluga")


@router.post("/models/{mid}/sizes", status_code=201)
def add_usluga_model_size(
    mid: int,
    payload: ModelSizeIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.add_size(mid, payload, db, current, "usluga")


@router.delete("/models/{mid}/sizes/{size_id}", status_code=204)
def delete_usluga_model_size(
    mid: int,
    size_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.delete_size(mid, size_id, db, current, "usluga")


@router.post("/models/{mid}/colors", status_code=201)
def add_usluga_model_color(
    mid: int,
    payload: ModelColorIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.add_color(mid, payload, db, current, "usluga")


@router.post("/models/{mid}/bom", status_code=201)
def add_usluga_model_bom(
    mid: int,
    payload: ModelBOMIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.add_bom(mid, payload, db, current, "usluga")


@router.post("/models/{mid}/bom-photo/upload", status_code=201)
async def upload_usluga_model_bom_photo(
    mid: int,
    db: DbSession,
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return await catalog_routes.upload_bom_photo(mid, db, file, current, "usluga")


@router.patch("/models/{mid}/bom/{bom_id}")
def update_usluga_model_bom(
    mid: int,
    bom_id: int,
    payload: ModelBOMUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.update_bom(mid, bom_id, payload, db, current, "usluga")


@router.delete("/models/{mid}/bom/{bom_id}", status_code=204)
def delete_usluga_model_bom(
    mid: int,
    bom_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    return catalog_routes.delete_bom(mid, bom_id, db, current, "usluga")


@router.delete("/models/{mid}", status_code=204)
def delete_usluga_model(mid: int, db: DbSession, current: User = Depends(require_permissions("usluga.manage", "*"))):
    _require_eco(current)
    return catalog_routes.delete_model(mid, db, current, "usluga")


@router.get("/orders")
def list_usluga_orders(
    db: DbSession,
    current: User = Depends(require_permissions("usluga.view", "usluga.manage", "usluga.handover", "*")),
    status: str | None = Query(default=None, max_length=32),
):
    _require_eco(current)
    query = db.query(ProductionOrder).filter(ProductionOrder.source_type == "usluga")
    if status:
        query = query.filter(ProductionOrder.status == status)
    return [_order_payload(db, row) for row in query.order_by(ProductionOrder.id.desc()).all()]


@router.get("/orders/{order_id}")
def get_usluga_order(
    order_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.view", "usluga.manage", "usluga.handover", "*")),
):
    _require_eco(current)
    return _order_payload(db, _require_usluga_order(db, order_id))


@router.post("/orders", status_code=201)
def create_usluga_order(
    payload: UslugaOrderIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    model = _usluga_model_query(db).filter(Model.id == payload.model_id).one_or_none()
    if not model:
        raise HTTPException(404, "Usluga model not found")
    plan_lines = _normalized_plan_lines(payload, model)
    items = [
        {
            "model_id": model.id,
            "color": row.color,
            "size": row.size,
            "planned_quantity": row.quantity,
            "printing_required": False,
        }
        for row in plan_lines
    ]
    order = create_production_order(
        db,
        production_type="service_order",
        source_type="usluga",
        model_id=model.id,
        planned_quantity=sum(row.quantity for row in plan_lines),
        deadline=payload.deadline,
        estimated_material_amount=None,
        estimated_material_unit=None,
        fabric_batch_id=None,
        destination_warehouse_id=None,
        items=items,
        created_by=current.id,
        service_customer_name=payload.customer_name,
        service_customer_reference=payload.customer_reference,
        service_material_description=payload.material_description,
        service_material_usage_kg=payload.material_usage_kg,
        service_material_notes=payload.material_notes,
    )
    create_work_orders(
        db,
        order.id,
        include_printing=False,
        cutting_department_code="ECT",
        factory_code="ECO",
        include_storage_transfer=False,
    )
    log_action(
        db,
        current,
        "create",
        "UslugaOrder",
        order.id,
        new_value={"order_no": order.production_no, "customer": order.service_customer_name},
    )
    db.commit()
    db.refresh(order)
    return _order_payload(db, order)


@router.patch("/orders/{order_id}")
def update_usluga_order(
    order_id: int,
    payload: UslugaOrderUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    order = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.id == order_id, ProductionOrder.source_type == "usluga")
        .with_for_update(of=ProductionOrder)
        .one_or_none()
    )
    if not order:
        raise HTTPException(404, "Usluga order not found")
    if order.handed_over_at:
        raise HTTPException(409, "Handed-over Usluga orders are read-only")

    model = _usluga_model_query(db).filter(Model.id == payload.model_id).one_or_none()
    if not model:
        raise HTTPException(404, "Usluga model not found")
    plan_lines = _normalized_plan_lines(payload, model)
    existing_items = (
        db.query(ProductionOrderItem)
        .filter(ProductionOrderItem.production_order_id == order.id)
        .order_by(ProductionOrderItem.id)
        .all()
    )
    structure_changed = _plan_signature(order.model_id, existing_items) != _plan_signature(model.id, plan_lines)
    if structure_changed:
        blocker = _structural_edit_blocker(db, order)
        if blocker:
            raise HTTPException(
                409,
                f"Model and planned quantities are locked because production has started: {blocker}. "
                "Customer, deadline, and material details can still be edited.",
            )

    before = {
        "customer_name": order.service_customer_name,
        "customer_reference": order.service_customer_reference,
        "model_id": order.model_id,
        "planned_quantity": int(order.planned_quantity or 0),
        "deadline": order.deadline,
        "material_description": order.service_material_description,
        "material_usage_kg": float(order.service_material_usage_kg) if order.service_material_usage_kg is not None else None,
        "material_notes": order.service_material_notes,
        "items": [
            {"color": row.color, "size": row.size, "quantity": int(row.planned_quantity or 0)}
            for row in existing_items
        ],
    }
    order.service_customer_name = payload.customer_name
    order.service_customer_reference = _clean(payload.customer_reference)
    order.deadline = payload.deadline
    order.service_material_description = _clean(payload.material_description)
    order.service_material_usage_kg = (
        Decimal(str(payload.material_usage_kg)) if payload.material_usage_kg is not None else None
    )
    order.service_material_notes = _clean(payload.material_notes)

    if structure_changed:
        total_quantity = sum(row.quantity for row in plan_lines)
        order.model_id = model.id
        order.planned_quantity = total_quantity
        for item in existing_items:
            db.delete(item)
        db.flush()
        for row in plan_lines:
            db.add(ProductionOrderItem(
                production_order_id=order.id,
                model_id=model.id,
                color=row.color,
                size=row.size,
                planned_quantity=row.quantity,
                printing_required=False,
            ))
        for work_order in db.query(WorkOrder).filter(WorkOrder.production_order_id == order.id).all():
            work_order.planned_input_qty = total_quantity
            work_order.planned_output_qty = total_quantity

    for work_order in db.query(WorkOrder).filter(WorkOrder.production_order_id == order.id).all():
        work_order.deadline = payload.deadline

    log_action(
        db,
        current,
        "update",
        "UslugaOrder",
        order.id,
        old_value=before,
        new_value={
            "customer_name": order.service_customer_name,
            "customer_reference": order.service_customer_reference,
            "model_id": order.model_id,
            "planned_quantity": int(order.planned_quantity or 0),
            "deadline": order.deadline,
            "material_description": order.service_material_description,
            "material_usage_kg": (
                float(order.service_material_usage_kg) if order.service_material_usage_kg is not None else None
            ),
            "material_notes": order.service_material_notes,
            "items": [
                {"color": row.color, "size": row.size, "quantity": row.quantity}
                for row in plan_lines
            ],
            "structure_changed": structure_changed,
        },
    )
    db.commit()
    db.refresh(order)
    return _order_payload(db, order)


@router.patch("/orders/{order_id}/material")
def update_usluga_material(
    order_id: int,
    payload: UslugaMaterialIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.manage", "*")),
):
    _require_eco(current)
    order = _require_usluga_order(db, order_id)
    if order.handed_over_at:
        raise HTTPException(409, "Handed-over Usluga orders are read-only")
    before = {
        "material_usage_kg": float(order.service_material_usage_kg or 0),
        "material_description": order.service_material_description,
        "material_notes": order.service_material_notes,
    }
    order.service_material_usage_kg = Decimal(str(payload.material_usage_kg))
    order.service_material_description = _clean(payload.material_description)
    order.service_material_notes = _clean(payload.material_notes)
    log_action(db, current, "update_material", "UslugaOrder", order.id, old_value=before)
    db.commit()
    return _order_payload(db, order)


@router.post("/orders/{order_id}/handover")
def hand_over_usluga_order(
    order_id: int,
    payload: UslugaHandoverIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.handover", "*")),
):
    _require_eco(current)
    order = _require_usluga_order(db, order_id)
    if order.handed_over_at:
        raise HTTPException(409, "Usluga order was already handed over")
    summary = _order_payload(db, order)
    if not summary["ready_for_handover"]:
        raise HTTPException(409, "Complete packaging and create all packages before handover")
    packages = db.query(Package).filter(Package.production_order_id == order.id).all()
    package_ids = [row.id for row in packages]
    if db.query(FinishedGoodsStock.id).filter(FinishedGoodsStock.package_id.in_(package_ids)).first():
        raise HTTPException(409, "Usluga packages must not create finished-goods stock")
    now = datetime.now(timezone.utc)
    for package in packages:
        if package.status != "packed":
            raise HTTPException(409, f"Package {package.package_no} is not ready for direct handover")
        package.status = "handed_over"
        db.add(PackageScanLog(package_id=package.id, scanned_by=current.id, scan_type="usluga_handover"))
    order.service_handover_recipient = payload.recipient
    order.service_handover_notes = _clean(payload.notes)
    order.handed_over_at = now
    order.handed_over_by = current.id
    order.status = "handed_over"
    log_action(
        db,
        current,
        "handover",
        "UslugaOrder",
        order.id,
        new_value={"recipient": payload.recipient, "package_ids": package_ids},
    )
    db.commit()
    return _order_payload(db, order)

from copy import deepcopy
from datetime import date, datetime, timezone
import os
import re
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Depends
from fastapi import UploadFile, File, Form
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.core.config import settings
from app.core.dt import date_filter_bounds
from app.core.uploads import (
    SAFE_DOCUMENT_EXTENSIONS,
    SAFE_IMAGE_EXTENSIONS,
    extension_for_upload,
    read_validated_image_upload,
    safe_content_type,
    read_validated_upload_content,
)
from app.models import (
    Brand, Collection, CollectionModel, Model, ModelImage, ModelSize, ModelColor, ModelBOM, User,
    Item, SalesOrderItem, ProductionOrder, ProductionOrderItem, Bundle, Package, PackageItem, FinishedGoodsStock,
    StockBatch,
)
from app.schemas.catalog import (
    BrandIn, BrandOut, CollectionIn, CollectionOut,
    ModelIn, ModelOut, ModelDetail, ModelImageIn, ModelImageOut, ModelSizeIn, ModelColorIn, ModelBOMIn,
    ModelBOMUpdate, ModelVariantCreateIn, ModelVariantUpdateIn,
)
from app.services.audit import log_action
from app.services.model_images import model_display_image_url, model_variant_picture_url

router = APIRouter(tags=["catalog"])


def _estimate_variant_net_cost_pc(db: DbSession, model: Model) -> float:
    """Estimate per-piece net cost from BOM default costs and costing percentages."""
    item_ids = {int(row.item_id) for row in (model.bom or []) if row.item_id}
    item_cost_map = {
        int(item.id): float(item.default_cost or 0)
        for item in (db.query(Item).filter(Item.id.in_(item_ids)).all() if item_ids else [])
    }
    base_cost = 0.0
    for row in model.bom or []:
        item_cost = item_cost_map.get(int(row.item_id), 0.0)
        base_cost += float(row.quantity_per_piece or 0) * (1.0 + float(row.waste_percent or 0) / 100.0) * item_cost

    details = model.details_json or {}
    costing = details.get("costing", {}) if isinstance(details, dict) else {}
    labor_pct = float(costing.get("labor_pct") or 12)
    electricity_pct = float(costing.get("electricity_pct") or 4)
    other_pct = float(costing.get("other_pct") or 3)
    return round(base_cost * (1.0 + (labor_pct + electricity_pct + other_pct) / 100.0), 2)


def _pagination_payload(rows: list[dict], *, total: int, page: int, page_size: int) -> dict:
    safe_page = max(1, int(page or 1))
    safe_size = max(1, min(int(page_size or 50), 500))
    return {"rows": rows, "total": int(total), "page": safe_page, "page_size": safe_size}


def _collection_payload(c: Collection) -> dict:
    return CollectionOut.model_validate(c).model_dump()


def _is_preview_image(img: ModelImage) -> bool:
    content_type = str(img.content_type or "").lower()
    file_name = str(img.file_name or img.file_url or "").lower()
    return content_type.startswith("image/") or file_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))


def _validate_file_url(file_url: str) -> str:
    value = file_url.strip()
    lowered = value.lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:", "file:")):
        raise HTTPException(400, "Unsupported file URL")
    if value.startswith("/storage/model-files/") or value.startswith(("https://", "http://")):
        return value
    raise HTTPException(400, "File URL must be an uploaded file path or an http(s) URL")


def _normalize_image_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    allowed = {"model", "material", "pattern"}
    if normalized not in allowed:
        raise HTTPException(400, "Image type must be model, material, or pattern")
    return normalized


def _image_payload(img: ModelImage) -> dict:
    return ModelImageOut.model_validate(img).model_dump()


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _normalized_key(value: object) -> str:
    return " ".join(_clean_text(value).casefold().split())


def _natural_sort_key(value: object) -> list[tuple[int, object]]:
    parts = re.split(r"(\d+)", _clean_text(value))
    return [(0, int(part)) if part.isdigit() else (1, part.casefold()) for part in parts if part]


def _model_code_parts_from_general(code: object, general: object) -> tuple[str, str]:
    code_model_no, code_variant_no = _split_model_code(_clean_text(code))
    if not isinstance(general, dict):
        general = {}
    configured_model_no = _clean_text(general.get("model_no") or general.get("modelNo"))
    model_no = configured_model_no or code_model_no
    configured_variant_no = _clean_text(general.get("variant_no") or general.get("variantNo"))
    # Once a model number is explicitly configured, an absent variant number means this
    # is the base model. Do not reinterpret a dash in the model number as a variant.
    variant_no = configured_variant_no if configured_model_no else code_variant_no
    return model_no, variant_no


def _model_code_parts(model: Model) -> tuple[str, str]:
    details = model.details_json or {}
    general = details.get("general") if isinstance(details, dict) else {}
    return _model_code_parts_from_general(model.code, general)


def _primary_model_image(model: Model) -> ModelImage | None:
    images = sorted(list(model.images or []), key=lambda img: int(getattr(img, "id", 0) or 0), reverse=True)
    primary_image = next((img for img in images if img.is_primary and img.image_type == "model" and _is_preview_image(img)), None)
    if not primary_image:
        primary_image = next((img for img in images if img.is_primary and _is_preview_image(img)), None)
    if not primary_image:
        primary_image = next((img for img in images if img.image_type == "model" and _is_preview_image(img)), None)
    if not primary_image:
        primary_image = next((img for img in images if _is_preview_image(img)), None)
    return primary_image


def _material_model_image(model: Model) -> ModelImage | None:
    images = sorted(
        list(model.images or []),
        key=lambda img: int(getattr(img, "id", 0) or 0),
        reverse=True,
    )
    return next(
        (img for img in images if img.image_type == "material" and _is_preview_image(img)),
        None,
    )


def _material_bom_rows(model: Model) -> list[ModelBOM]:
    rows: list[ModelBOM] = []
    for row in model.bom or []:
        item = getattr(row, "item", None)
        category = str(getattr(item, "category", "") or "").lower()
        if category in {"fabric", "semi_finished", ""}:
            rows.append(row)
    return rows


def _composition_label(rows: list[dict] | None) -> str:
    parts: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = _clean_text(row.get("name"))
        if not name:
            continue
        percentage = row.get("percentage")
        try:
            pct = float(percentage or 0)
        except (TypeError, ValueError):
            pct = 0
        parts.append(f"{name} {pct:g}%" if pct else name)
    return ", ".join(parts)


def _details_variant_fabric(model: Model) -> str:
    details = model.details_json or {}
    general = details.get("general") if isinstance(details, dict) else {}
    if not isinstance(general, dict):
        return ""
    return _clean_text(general.get("variant_fabric") or general.get("variantFabric"))


def _fabric_item_label(item: Item | None) -> str:
    if not item:
        return ""
    name = _clean_text(item.name)
    sku = _clean_text(item.sku)
    return name or sku


def _selected_variant_fabric_item(
    db: DbSession,
    fabric_item_id: int | None,
    legacy_stock_batch_id: int | None = None,
) -> Item:
    item_id = int(fabric_item_id or 0)
    if not item_id and legacy_stock_batch_id:
        legacy_batch = db.get(StockBatch, int(legacy_stock_batch_id))
        if not legacy_batch:
            raise HTTPException(404, "Fabric stock batch not found")
        item_id = int(legacy_batch.item_id)
    item = db.get(Item, item_id) if item_id else None
    if not item:
        raise HTTPException(404, "Fabric type not found")
    if str(item.category or "").lower() not in {"fabric", "semi_finished"}:
        raise HTTPException(400, "Selected item must be a fabric type from inventory master data")
    if not item.is_active:
        raise HTTPException(400, "Selected fabric type is inactive")
    return item


def _variant_fabric_item_id_for_model(model: Model) -> int | None:
    for row in _material_bom_rows(model):
        if row.item_id:
            return int(row.item_id)
    details = model.details_json or {}
    general = details.get("general") if isinstance(details, dict) else {}
    if not isinstance(general, dict):
        return None
    try:
        value = int(general.get("variant_fabric_item_id") or 0)
    except (TypeError, ValueError):
        return None
    return value or None


def _set_variant_general_details(
    model: Model,
    *,
    model_no: str,
    variant_no: str,
    fabric_item: Item | None = None,
) -> None:
    details = deepcopy(model.details_json or {})
    general = details.get("general")
    if not isinstance(general, dict):
        general = {}
    general["model_no"] = model_no
    general["variant_no"] = variant_no
    if fabric_item is not None:
        general["variant_fabric"] = _fabric_item_label(fabric_item)
        general["variant_fabric_item_id"] = int(fabric_item.id)
        general.pop("variant_stock_batch_id", None)
    details["general"] = general
    model.details_json = details


def _set_variant_material_image(db: DbSession, model: Model, picture_url: str) -> None:
    material_images = sorted(
        [img for img in (model.images or []) if img.image_type == "material"],
        key=lambda img: int(getattr(img, "id", 0) or 0),
        reverse=True,
    )
    file_name = os.path.basename(picture_url.split("?", 1)[0]) or None
    extension = os.path.splitext(file_name or "")[1].lower()
    content_type = safe_content_type(extension) if extension in SAFE_IMAGE_EXTENSIONS else None
    if material_images:
        image = material_images[0]
        image.file_url = picture_url
        image.file_name = file_name
        image.content_type = content_type
        image.file_data = None
        image.is_primary = False
        return
    db.add(
        ModelImage(
            model_id=model.id,
            file_url=picture_url,
            file_name=file_name,
            content_type=content_type,
            image_type="material",
            is_primary=False,
        )
    )


def _apply_variant_fabric_item(
    model: Model,
    selected_item: Item,
    *,
    color: str | None = None,
    picture_url: str | None = None,
) -> None:
    fabric_row = next(iter(_material_bom_rows(model)), None)
    if not fabric_row:
        raise HTTPException(400, "Add a fabric BOM row to this model before editing variants")
    fabric_item_changed = int(fabric_row.item_id or 0) != int(selected_item.id)
    fabric_row.item_id = int(selected_item.id)
    fabric_row.stock_batch_id = None
    fabric_row.color = _clean_text(color) or None
    if picture_url is not None:
        fabric_row.photo_url = picture_url
    elif fabric_item_changed:
        fabric_row.photo_url = None
    fabric_row.unit = selected_item.unit or fabric_row.unit


def _fabric_label_for_model(model: Model) -> str:
    for row in _material_bom_rows(model):
        item = getattr(row, "item", None)
        item_name = _clean_text(getattr(item, "name", None))
        item_sku = _clean_text(getattr(item, "sku", None))
        color = _clean_text(row.color)
        parts: list[str] = []
        if item_name:
            parts.append(item_name)
        elif item_sku:
            parts.append(item_sku)
        if color and item_name and _normalized_key(item_name) in _normalized_key(color):
            parts = [color]
        elif color and item_sku and _normalized_key(item_sku) in _normalized_key(color):
            parts = [color]
        elif color and _normalized_key(color) not in _normalized_key(" ".join(parts)):
            parts.append(color)
        label = " / ".join(parts)
        if label:
            return label
    return _details_variant_fabric(model) or _composition_label(model.material_composition)


def _variant_picture_url_for_model(model: Model) -> str | None:
    return model_variant_picture_url(model)


def _fabric_picture_url_for_model(model: Model) -> str | None:
    material_image = _material_model_image(model)
    if material_image:
        return material_image.file_url
    for row in _material_bom_rows(model):
        item = getattr(row, "item", None)
        picture = row.photo_url or getattr(item, "image_url", None)
        if picture:
            return picture
    return None


def _model_variant_payload(model: Model) -> dict:
    model_no, variant_no = _model_code_parts(model)
    fabric = _fabric_label_for_model(model)
    picture_url = _variant_picture_url_for_model(model)
    fabric_item_id = _variant_fabric_item_id_for_model(model)
    fabric_row = next(iter(_material_bom_rows(model)), None)
    return {
        "id": model.id,
        "model_id": model.id,
        "code": model.code,
        "name": model.name,
        "category": model.category,
        "status": model.status,
        "created_at": model.created_at,
        "model_no": model_no,
        "variant_no": variant_no,
        "fabric": fabric,
        "picture_url": picture_url,
        "fabric_item_id": fabric_item_id,
        "color": _clean_text(getattr(fabric_row, "color", None)) or None,
        "stock_batch_id": None,
    }


def _model_group_key_from_values(*, model_id: int, code: object, name: object, general: object) -> str:
    model_no, _ = _model_code_parts_from_general(code, general)
    if model_no:
        return f"model:{_normalized_key(model_no)}"
    if name:
        return f"name:{_normalized_key(name)}"
    return f"id:{model_id}"


def _model_group_key(model: Model) -> str:
    details = model.details_json or {}
    general = details.get("general") if isinstance(details, dict) else {}
    return _model_group_key_from_values(
        model_id=int(model.id),
        code=model.code,
        name=model.name,
        general=general,
    )


def _group_display_name(models: list[Model]) -> str:
    counts: dict[str, int] = {}
    original: dict[str, str] = {}
    for model in models:
        name = _clean_text(model.name)
        if not name:
            continue
        key = _normalized_key(name)
        counts[key] = counts.get(key, 0) + 1
        original.setdefault(key, name)
    if not counts:
        return _clean_text(models[0].name) if models else ""
    best_key = sorted(counts, key=lambda key: (-counts[key], len(original[key]), original[key].casefold()))[0]
    return original[best_key]


def _compact_model_details(details: object) -> dict | None:
    if not isinstance(details, dict):
        return None
    compact: dict = {}
    general = details.get("general")
    if isinstance(general, dict):
        compact_general = {
            key: deepcopy(general[key])
            for key in ("model_no", "modelNo", "variant_no", "variantNo")
            if key in general
        }
        if compact_general:
            compact["general"] = compact_general
    for key in ("translation", "composition"):
        if key in details:
            compact[key] = deepcopy(details[key])
    return compact


def _compact_model_payload(model: Model) -> dict:
    images = sorted(
        list(model.images or []),
        key=lambda img: int(getattr(img, "id", 0) or 0),
        reverse=True,
    )
    primary_image = _primary_model_image(model)
    primary_payload = _image_payload(primary_image) if primary_image else None
    variant_payload = _model_variant_payload(model)
    return {
        "id": model.id,
        "code": model.code,
        "name": model.name,
        "category": model.category,
        "details_json": _compact_model_details(model.details_json),
        "status": model.status,
        "created_at": model.created_at,
        "sam_minutes": model.sam_minutes,
        "material_composition": model.material_composition,
        "primary_image": primary_payload,
        "primary_image_url": (
            primary_payload["file_url"]
            if primary_payload
            else model_display_image_url(model)
        ),
        "image_count": len(images),
        "variant_no": variant_payload["variant_no"],
        "variant_fabric": variant_payload["fabric"],
        "variant_picture_url": variant_payload["picture_url"],
        "fabric_image_url": _fabric_picture_url_for_model(model),
    }


def _model_group_payload(models: list[Model], *, compact: bool = False) -> dict:
    ordered_models = sorted(models, key=lambda model: _natural_sort_key(_model_code_parts(model)[1] or model.code))
    variants = [
        _model_variant_payload(model)
        for model in ordered_models
        if _clean_text(_model_code_parts(model)[1])
    ]
    representative = max(models, key=lambda model: int(model.id or 0))
    payload = _compact_model_payload(representative) if compact else _model_payload(representative)
    group_model_no, _ = _model_code_parts(representative)
    group_picture = None
    for model in ordered_models:
        model_image = _primary_model_image(model)
        if model_image:
            group_picture = model_image.file_url
            break
    payload.update({
        "group_key": _model_group_key(representative),
        "group_model_no": group_model_no,
        "group_name": _group_display_name(models),
        "name": _group_display_name(models),
        "variant_count": len(variants),
        "variants": variants,
        "primary_image_url": group_picture or payload.get("primary_image_url"),
    })
    return payload


def _model_payload(m: Model) -> dict:
    payload = ModelOut.model_validate(m).model_dump()
    images = sorted(list(m.images or []), key=lambda img: int(getattr(img, "id", 0) or 0), reverse=True)
    primary_image = _primary_model_image(m)
    primary_payload = _image_payload(primary_image) if primary_image else None
    variant_payload = _model_variant_payload(m)
    payload["primary_image"] = primary_payload
    payload["primary_image_url"] = primary_payload["file_url"] if primary_payload else model_display_image_url(m)
    payload["image_count"] = len(images)
    payload["variant_no"] = variant_payload["variant_no"]
    payload["variant_fabric"] = variant_payload["fabric"]
    payload["variant_picture_url"] = variant_payload["picture_url"]
    payload["fabric_image_url"] = _fabric_picture_url_for_model(m)
    return payload


def _models_query(db: DbSession):
    return db.query(Model).options(
        selectinload(Model.images).load_only(
            ModelImage.id,
            ModelImage.model_id,
            ModelImage.file_url,
            ModelImage.file_name,
            ModelImage.content_type,
            ModelImage.image_type,
            ModelImage.is_primary,
            ModelImage.created_at,
        ),
        selectinload(Model.bom).joinedload(ModelBOM.item),
        selectinload(Model.bom).joinedload(ModelBOM.stock_batch),
    )


def _without_internal_legacy_models(qry):
    """Keep migration-only stock identities out of the PLM catalog."""
    legacy_flag = Model.details_json["legacy_import"].as_boolean()
    return qry.filter(func.coalesce(legacy_flag, False).is_(False))


def _apply_model_list_filters(
    qry,
    *,
    status: str | None,
    q: str | None,
    code: str | None,
    name: str | None,
    category: str | None,
    created_from: date | None,
    created_to: date | None,
    include_legacy_import: bool,
):
    if not include_legacy_import:
        qry = _without_internal_legacy_models(qry)
    if status:
        qry = qry.filter(Model.status == status)
    search_query = _clean_text(q)
    if search_query:
        pattern = f"%{search_query}%"
        qry = qry.filter(
            (Model.name.ilike(pattern))
            | (Model.code.ilike(pattern))
            | (Model.category.ilike(pattern))
        )
    code_query = _clean_text(code)
    if code_query:
        qry = qry.filter(Model.code.ilike(f"%{code_query}%"))
    name_query = _clean_text(name)
    if name_query:
        qry = qry.filter(Model.name.ilike(f"%{name_query}%"))
    category_query = _clean_text(category)
    if category_query:
        qry = qry.filter(Model.category.ilike(f"%{category_query}%"))
    start, end = date_filter_bounds(created_from, created_to)
    if start:
        qry = qry.filter(Model.created_at >= start)
    if end:
        qry = qry.filter(Model.created_at <= end)
    return qry


def _model_group_member_ids(qry) -> list[list[int]]:
    grouped: dict[str, list[int]] = {}
    for row in qry.order_by(Model.id.desc()).all():
        key = _model_group_key_from_values(
            model_id=int(row.id),
            code=row.code,
            name=row.name,
            general=row.general_details,
        )
        grouped.setdefault(key, []).append(int(row.id))
    return list(grouped.values())


def _model_with_variant_relations(db: DbSession, mid: int) -> Model | None:
    return (
        db.query(Model)
        .options(
            selectinload(Model.images),
            selectinload(Model.sizes),
            selectinload(Model.colors),
            selectinload(Model.bom).joinedload(ModelBOM.item),
            selectinload(Model.bom).joinedload(ModelBOM.stock_batch),
        )
        .filter(Model.id == mid)
        .first()
    )


def _model_usage_blockers(db: DbSession, mid: int) -> list[str]:
    blockers: list[str] = []
    if db.query(SalesOrderItem).filter(SalesOrderItem.model_id == mid).first():
        blockers.append("sales orders")
    if db.query(ProductionOrder).filter(ProductionOrder.model_id == mid).first():
        blockers.append("production orders")
    if db.query(ProductionOrderItem).filter(ProductionOrderItem.model_id == mid).first():
        blockers.append("production order items")
    if db.query(Bundle).filter(Bundle.model_id == mid).first():
        blockers.append("bundles")
    if db.query(Package).filter(Package.model_id == mid).first():
        blockers.append("packages")
    if db.query(PackageItem).filter(PackageItem.model_id == mid).first():
        blockers.append("package items")
    if db.query(FinishedGoodsStock).filter(FinishedGoodsStock.model_id == mid).first():
        blockers.append("finished goods stock")
    return blockers


def _normalize_bom_batch_fields(db: DbSession, data: dict) -> dict:
    item_id = int(data.get("item_id") or 0)
    item = db.get(Item, item_id) if item_id else None
    if not item:
        raise HTTPException(404, "Inventory master item not found")
    if str(item.category or "").lower() in {"fabric", "semi_finished"}:
        data["stock_batch_id"] = None
        if not data.get("unit"):
            data["unit"] = item.unit
        return data
    stock_batch_id = data.get("stock_batch_id")
    if not stock_batch_id:
        data["stock_batch_id"] = None
        return data
    batch = db.get(StockBatch, int(stock_batch_id))
    if not batch:
        raise HTTPException(404, "Stock batch not found")
    if item_id and item_id != int(batch.item_id):
        raise HTTPException(400, "Stock batch does not belong to selected item")
    data["item_id"] = int(batch.item_id)
    if not data.get("color") and batch.color:
        data["color"] = batch.color
    if not data.get("photo_url") and batch.image_url:
        data["photo_url"] = batch.image_url
    return data


def _split_model_code(code: str | None) -> tuple[str, str]:
    value = str(code or "").strip()
    dash_index = value.rfind("-")
    if 0 < dash_index < len(value) - 1:
        return value[:dash_index], value[dash_index + 1:]
    return value, ""


def _build_model_code(model_no: str, variant_no: str) -> str:
    clean_model_no = _clean_text(model_no)
    clean_variant_no = _clean_text(variant_no)
    if clean_model_no and clean_variant_no:
        return f"{clean_model_no}-{clean_variant_no}"
    return clean_model_no or clean_variant_no


def _set_model_identity(model: Model, *, model_no: str, variant_no: str) -> None:
    model.code = _build_model_code(model_no, variant_no)
    details = deepcopy(model.details_json or {})
    general = details.get("general")
    if not isinstance(general, dict):
        general = {}
    general["model_no"] = _clean_text(model_no)
    if variant_no:
        general["variant_no"] = _clean_text(variant_no)
    else:
        general.pop("variant_no", None)
        general.pop("variantNo", None)
    details["general"] = general
    model.details_json = details


def _rename_model_group(db: DbSession, source: Model, new_model_no: str) -> list[tuple[Model, str]]:
    """Rename every variant in source's current group while preserving variant numbers."""
    old_model_no, _ = _model_code_parts(source)
    clean_new_model_no = _clean_text(new_model_no)
    if not old_model_no or not clean_new_model_no:
        raise HTTPException(400, "Model number is required")
    if _normalized_key(old_model_no) == _normalized_key(clean_new_model_no):
        return []

    old_group_key = _normalized_key(old_model_no)
    group = [
        model
        for model in db.query(Model).all()
        if _normalized_key(_model_code_parts(model)[0]) == old_group_key
    ]
    if not group:
        group = [source]

    planned: list[tuple[Model, str, str]] = []
    planned_codes: set[str] = set()
    for model in group:
        _, variant_no = _model_code_parts(model)
        next_code = _build_model_code(clean_new_model_no, variant_no)
        normalized_code = _normalized_key(next_code)
        if normalized_code in planned_codes:
            raise HTTPException(409, f"Model number change would duplicate variant {variant_no or next_code}")
        planned_codes.add(normalized_code)
        planned.append((model, variant_no, next_code))

    group_ids = [int(model.id) for model in group]
    external_models = db.query(Model).filter(~Model.id.in_(group_ids)).all()
    external_by_code = {_normalized_key(model.code): model for model in external_models}
    for _, variant_no, next_code in planned:
        if _normalized_key(next_code) in external_by_code:
            raise HTTPException(
                409,
                f"Model number change conflicts with existing variant {variant_no or next_code}",
            )

    renamed: list[tuple[Model, str]] = []
    for model, variant_no, _ in planned:
        old_code = model.code
        _set_model_identity(model, model_no=clean_new_model_no, variant_no=variant_no)
        renamed.append((model, old_code))
    return renamed


def _unique_model_copy_code(db: DbSession, source_code: str) -> str:
    for index in range(1, 10_000):
        suffix = "-COPY" if index == 1 else f"-COPY-{index}"
        base = source_code[: max(1, 64 - len(suffix))]
        candidate = f"{base}{suffix}"
        if not db.query(Model.id).filter(Model.code == candidate).first():
            return candidate
    raise HTTPException(409, "Could not create a unique cloned model code")


def _clone_details_for_code(details: dict | None, new_code: str) -> dict:
    copied = deepcopy(details or {})
    general = copied.get("general")
    if not isinstance(general, dict):
        general = {}
    model_no, variant_no = _split_model_code(new_code)
    general["model_no"] = model_no
    general["variant_no"] = variant_no
    copied["general"] = general
    return copied


# ===== Brands =====
@router.get("/brands", response_model=list[BrandOut])
def list_brands(db: DbSession, _: CurrentUser):
    return db.query(Brand).order_by(Brand.name).all()


@router.post("/brands", response_model=BrandOut, status_code=201)
def create_brand(
    payload: BrandIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.brands", "planning.production", "*")),
):
    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(400, "Brand name is required")
    existing = db.query(Brand).filter(func.lower(Brand.name) == name.lower()).first()
    if existing:
        raise HTTPException(409, "Brand already exists")
    values = payload.model_dump()
    values["name"] = name
    b = Brand(**values)
    db.add(b); db.flush()
    log_action(db, current, "create", "Brand", b.id)
    db.commit(); db.refresh(b)
    return b


@router.get("/brands/{bid}", response_model=BrandOut)
def get_brand(bid: int, db: DbSession, _: CurrentUser):
    b = db.get(Brand, bid)
    if not b: raise HTTPException(404, "Brand not found")
    return b


@router.patch("/brands/{bid}", response_model=BrandOut)
def update_brand(bid: int, payload: BrandIn, db: DbSession, current: User = Depends(require_permissions("modeling.brands", "*"))):
    b = db.get(Brand, bid)
    if not b: raise HTTPException(404, "Brand not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    log_action(db, current, "update", "Brand", b.id)
    db.commit(); db.refresh(b)
    return b


# ===== Collections =====
@router.get("/collections")
def list_collections(
    db: DbSession,
    _: CurrentUser,
    brand_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(Collection)
    if brand_id:
        qry = qry.filter(Collection.brand_id == brand_id)
    total = qry.count() if include_total else 0
    qry = qry.order_by(Collection.id.desc())
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.offset((safe_page - 1) * safe_size).limit(safe_size)
    rows = [_collection_payload(c) for c in qry.all()]
    if include_total:
        return _pagination_payload(rows, total=total, page=page, page_size=page_size)
    return rows


@router.post("/collections", response_model=CollectionOut, status_code=201)
def create_collection(payload: CollectionIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    if not payload.year:
        raise HTTPException(400, "Year is required")
    c = Collection(**payload.model_dump())
    db.add(c); db.flush()
    log_action(db, current, "create", "Collection", c.id)
    db.commit(); db.refresh(c)
    return c


@router.get("/collections/seasons")
def list_collection_seasons(db: DbSession, _: CurrentUser):
    rows = (
        db.query(Collection.season)
        .filter(Collection.season.isnot(None), Collection.season != "")
        .group_by(Collection.season)
        .order_by(Collection.season.asc())
        .all()
    )
    return [season for (season,) in rows if season]


@router.get("/collections/{cid}", response_model=CollectionOut)
def get_collection(cid: int, db: DbSession, _: CurrentUser):
    c = db.get(Collection, cid)
    if not c: raise HTTPException(404, "Collection not found")
    return c


@router.patch("/collections/{cid}", response_model=CollectionOut)
def update_collection(cid: int, payload: CollectionIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    c = db.get(Collection, cid)
    if not c: raise HTTPException(404, "Collection not found")
    data = payload.model_dump(exclude_unset=True)
    if "year" in data and not data["year"]:
        raise HTTPException(400, "Year is required")
    for k, v in data.items():
        setattr(c, k, v)
    log_action(db, current, "update", "Collection", c.id)
    db.commit(); db.refresh(c)
    return c


@router.post("/collections/{cid}/models", status_code=201)
def add_model_to_collection(cid: int, model_id: int, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    if not db.get(Collection, cid):
        raise HTTPException(404, "Collection not found")
    if not db.get(Model, model_id):
        raise HTTPException(404, "Model not found")
    db.add(CollectionModel(collection_id=cid, model_id=model_id))
    db.commit()
    return {"message": "added"}


# ===== Models =====
@router.get("/models")
def list_models(
    db: DbSession,
    _: CurrentUser,
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
):
    qry = _apply_model_list_filters(
        _models_query(db),
        status=status,
        q=q,
        code=code,
        name=name,
        category=category,
        created_from=created_from,
        created_to=created_to,
        include_legacy_import=include_legacy_import,
    )
    total = qry.count() if include_total else 0
    qry = qry.order_by(Model.id.desc())
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.offset((safe_page - 1) * safe_size).limit(safe_size)
    rows = [_model_payload(m) for m in qry.all()]
    if include_total:
        return _pagination_payload(rows, total=total, page=page, page_size=page_size)
    return rows


@router.get("/models/variant-groups")
def list_model_variant_groups(
    db: DbSession,
    _: CurrentUser,
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
    identity_qry = db.query(
        Model.id,
        Model.code,
        Model.name,
        Model.details_json["general"].label("general_details"),
    )
    identity_qry = _apply_model_list_filters(
        identity_qry,
        status=status,
        q=q,
        code=code,
        name=name,
        category=category,
        created_from=created_from,
        created_to=created_to,
        include_legacy_import=include_legacy_import,
    )
    grouped_ids = _model_group_member_ids(identity_qry)
    total = len(grouped_ids)
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        grouped_ids = grouped_ids[(safe_page - 1) * safe_size : safe_page * safe_size]

    member_ids = [model_id for group_ids in grouped_ids for model_id in group_ids]
    models_by_id = (
        {
            int(model.id): model
            for model in _models_query(db).filter(Model.id.in_(member_ids)).all()
        }
        if member_ids
        else {}
    )
    model_groups = [
        [models_by_id[model_id] for model_id in group_ids if model_id in models_by_id]
        for group_ids in grouped_ids
    ]
    rows = [
        _model_group_payload(models, compact=compact)
        for models in model_groups
        if models
    ]
    rows.sort(key=lambda row: int(row.get("id") or 0), reverse=True)
    if include_total:
        return _pagination_payload(rows, total=total, page=page, page_size=page_size)
    return rows


@router.post("/models", response_model=ModelOut, status_code=201)
def create_model(payload: ModelIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    if db.query(Model).filter(Model.code == payload.code).first():
        raise HTTPException(400, "Model code already exists")
    m = Model(**payload.model_dump(), created_by=current.id)
    db.add(m); db.flush()
    log_action(db, current, "create", "Model", m.id, new_value={"code": m.code})
    db.commit(); db.refresh(m)
    return m


@router.get("/models/{mid}", response_model=ModelDetail)
def get_model(mid: int, db: DbSession, _: CurrentUser):
    m = _models_query(db).filter(Model.id == mid).first()
    if not m: raise HTTPException(404, "Model not found")
    return m


@router.post("/models/{mid}/clone", response_model=ModelOut, status_code=201)
def clone_model(mid: int, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    source = (
        db.query(Model)
        .options(
            selectinload(Model.images),
            selectinload(Model.sizes),
            selectinload(Model.colors),
            selectinload(Model.bom),
        )
        .filter(Model.id == mid)
        .first()
    )
    if not source:
        raise HTTPException(404, "Model not found")

    new_code = _unique_model_copy_code(db, source.code)
    cloned = Model(
        code=new_code,
        name=f"{source.name} Copy",
        category=source.category,
        description=source.description,
        brand_id=source.brand_id,
        collection_id=source.collection_id,
        product_type=source.product_type,
        season=source.season,
        constructor_employee_id=source.constructor_employee_id,
        designer_employee_id=source.designer_employee_id,
        details_json=_clone_details_for_code(source.details_json, new_code),
        status="draft",
        created_by=current.id,
        sam_minutes=source.sam_minutes or 0,
    )
    db.add(cloned)
    db.flush()

    for row in source.sizes or []:
        db.add(ModelSize(model_id=cloned.id, size=row.size, measurement_json=deepcopy(row.measurement_json)))
    for row in source.colors or []:
        db.add(ModelColor(model_id=cloned.id, color_name=row.color_name, color_code=row.color_code))
    for row in source.bom or []:
        db.add(
            ModelBOM(
                model_id=cloned.id,
                item_id=row.item_id,
                stock_batch_id=row.stock_batch_id,
                size=row.size,
                color=row.color,
                photo_url=row.photo_url,
                quantity_per_piece=row.quantity_per_piece,
                unit=row.unit,
                waste_percent=row.waste_percent,
            )
        )
    for row in source.images or []:
        db.add(
            ModelImage(
                model_id=cloned.id,
                file_url=row.file_url,
                file_name=row.file_name,
                content_type=row.content_type,
                file_data=row.file_data,
                image_type=row.image_type,
                is_primary=row.is_primary,
            )
        )
    for row in db.query(CollectionModel).filter(CollectionModel.model_id == source.id).all():
        db.add(CollectionModel(collection_id=row.collection_id, model_id=cloned.id))

    log_action(db, current, "clone", "Model", cloned.id, new_value={"source_model_id": source.id, "code": cloned.code})
    db.commit()
    db.refresh(cloned)
    return cloned


@router.get("/models/{mid}/variants")
def list_model_variants(mid: int, db: DbSession, _: CurrentUser):
    """Return fabric variants that belong to the same model group."""
    m = _models_query(db).filter(Model.id == mid).first()
    if not m:
        raise HTTPException(404, "Model not found")

    group_key = _model_group_key(m)
    variants = [
        _model_variant_payload(model)
        for model in _models_query(db).all()
        if _model_group_key(model) == group_key and _clean_text(_model_code_parts(model)[1])
    ]
    variants.sort(key=lambda row: _natural_sort_key(row.get("variant_no") or row.get("code")))
    return variants


@router.post("/models/{mid}/variants", response_model=ModelOut, status_code=201)
def create_model_variant(
    mid: int,
    payload: ModelVariantCreateIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
):
    source = _model_with_variant_relations(db, mid)
    if not source:
        raise HTTPException(404, "Model not found")

    model_no, _ = _model_code_parts(source)
    model_no = _clean_text(model_no)
    variant_no = _clean_text(payload.variant_no)
    if not model_no:
        raise HTTPException(400, "Model number is required before adding variants")
    if not variant_no:
        raise HTTPException(400, "Variant number is required")

    selected_item = _selected_variant_fabric_item(db, payload.fabric_item_id, payload.stock_batch_id)
    color = _clean_text(payload.color) or None
    picture_url = _validate_file_url(payload.picture_url) if payload.picture_url else None
    source_fabric_row = next(iter(_material_bom_rows(source)), None)
    if not source_fabric_row:
        raise HTTPException(400, "Add a fabric BOM row to this model before creating variants")
    fabric = _fabric_item_label(selected_item)

    new_code = f"{model_no}-{variant_no}"
    if db.query(Model.id).filter(Model.code == new_code).first():
        raise HTTPException(400, "Model variant already exists")

    details = deepcopy(source.details_json or {})
    general = details.get("general")
    if not isinstance(general, dict):
        general = {}
    general["model_no"] = model_no
    general["variant_no"] = variant_no
    general["variant_fabric"] = fabric
    general["variant_fabric_item_id"] = int(selected_item.id)
    general.pop("variant_stock_batch_id", None)
    details["general"] = general

    approved = source.status == "approved"
    cloned = Model(
        code=new_code,
        name=source.name,
        category=source.category,
        description=source.description,
        brand_id=source.brand_id,
        collection_id=source.collection_id,
        product_type=source.product_type,
        season=source.season,
        constructor_employee_id=source.constructor_employee_id,
        designer_employee_id=source.designer_employee_id,
        details_json=details,
        status=source.status,
        created_by=current.id,
        approved_by=current.id if approved else None,
        approved_at=datetime.now(timezone.utc) if approved else None,
        sam_minutes=source.sam_minutes or 0,
    )
    db.add(cloned)
    db.flush()

    for row in source.sizes or []:
        db.add(ModelSize(model_id=cloned.id, size=row.size, measurement_json=deepcopy(row.measurement_json)))
    for row in source.colors or []:
        db.add(ModelColor(model_id=cloned.id, color_name=row.color_name, color_code=row.color_code))

    fabric_applied = False
    for row in source.bom or []:
        item = getattr(row, "item", None)
        category = str(getattr(item, "category", "") or "").lower()
        is_fabric_row = not fabric_applied and category in {"fabric", "semi_finished", ""}
        db.add(
            ModelBOM(
                model_id=cloned.id,
                item_id=selected_item.id if is_fabric_row else row.item_id,
                stock_batch_id=None if is_fabric_row else row.stock_batch_id,
                size=row.size,
                color=color if is_fabric_row else row.color,
                photo_url=picture_url if is_fabric_row else row.photo_url,
                quantity_per_piece=row.quantity_per_piece,
                unit=(selected_item.unit or row.unit) if is_fabric_row else row.unit,
                waste_percent=row.waste_percent,
            )
        )
        if is_fabric_row:
            fabric_applied = True

    copied_material_image = False
    for row in source.images or []:
        is_material_image = str(row.image_type or "").lower() == "material"
        copied_material_image = copied_material_image or is_material_image
        copied_file_url = picture_url if picture_url and is_material_image else row.file_url
        copied_file_name = (
            os.path.basename(picture_url.split("?", 1)[0]) or None
            if picture_url and is_material_image
            else row.file_name
        )
        copied_extension = os.path.splitext(copied_file_name or "")[1].lower()
        copied_content_type = (
            safe_content_type(copied_extension)
            if picture_url and is_material_image and copied_extension in SAFE_IMAGE_EXTENSIONS
            else row.content_type
        )
        db.add(
            ModelImage(
                model_id=cloned.id,
                file_url=copied_file_url,
                file_name=copied_file_name,
                content_type=copied_content_type,
                file_data=None if picture_url and is_material_image else row.file_data,
                image_type=row.image_type,
                is_primary=row.is_primary,
            )
        )
    if picture_url and not copied_material_image:
        _set_variant_material_image(db, cloned, picture_url)
    for row in db.query(CollectionModel).filter(CollectionModel.model_id == source.id).all():
        db.add(CollectionModel(collection_id=row.collection_id, model_id=cloned.id))

    log_action(
        db,
        current,
        "create_variant",
        "Model",
        cloned.id,
        new_value={
            "source_model_id": source.id,
            "code": cloned.code,
            "variant_no": variant_no,
            "fabric_item_id": int(selected_item.id),
            "fabric": fabric,
            "color": color,
            "picture_url": picture_url,
        },
    )
    db.commit()
    db.refresh(cloned)
    return cloned


@router.patch("/models/{mid}/variants/{variant_id}", response_model=ModelOut)
def update_model_variant(
    mid: int,
    variant_id: int,
    payload: ModelVariantUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
):
    source = _model_with_variant_relations(db, mid)
    if not source:
        raise HTTPException(404, "Model not found")
    target = _model_with_variant_relations(db, variant_id)
    if not target or _model_group_key(target) != _model_group_key(source):
        raise HTTPException(404, "Variant not found")

    model_no, _ = _model_code_parts(source)
    model_no = _clean_text(model_no)
    variant_no = _clean_text(payload.variant_no)
    if not model_no:
        raise HTTPException(400, "Model number is required before editing variants")
    if not variant_no:
        raise HTTPException(400, "Variant number is required")

    selected_item = (
        _selected_variant_fabric_item(db, payload.fabric_item_id, payload.stock_batch_id)
        if payload.fabric_item_id or payload.stock_batch_id
        else None
    )
    color = _clean_text(payload.color) or None
    picture_url = _validate_file_url(payload.picture_url) if payload.picture_url else None
    fabric = _fabric_item_label(selected_item) if selected_item else _details_variant_fabric(target)
    new_code = f"{model_no}-{variant_no}"
    duplicate = db.query(Model.id).filter(Model.code == new_code, Model.id != target.id).first()
    if duplicate:
        raise HTTPException(400, "Model variant already exists")

    old_value = {
        "code": target.code,
        "variant_no": _model_code_parts(target)[1],
        "fabric_item_id": _variant_fabric_item_id_for_model(target),
        "color": next((row.color for row in _material_bom_rows(target)), None),
    }
    target.code = new_code
    _set_variant_general_details(
        target,
        model_no=model_no,
        variant_no=variant_no,
        fabric_item=selected_item,
    )
    fabric_row = next(iter(_material_bom_rows(target)), None)
    if selected_item and fabric_row:
        _apply_variant_fabric_item(target, selected_item, color=color, picture_url=picture_url)
    elif fabric_row:
        if picture_url is not None:
            fabric_row.photo_url = picture_url
        if payload.color is not None:
            fabric_row.color = color
    elif picture_url is not None:
        _set_variant_material_image(db, target, picture_url)
    if picture_url is not None and fabric_row:
        _set_variant_material_image(db, target, picture_url)
    log_action(
        db,
        current,
        "update_variant",
        "Model",
        target.id,
        old_value=old_value,
        new_value={
            "source_model_id": source.id,
            "code": target.code,
            "variant_no": variant_no,
            "fabric_item_id": int(selected_item.id) if selected_item else None,
            "fabric": fabric,
            "color": color,
            "picture_url": picture_url,
        },
    )
    db.commit()
    db.refresh(target)
    return target


@router.delete("/models/{mid}/variants/{variant_id}", status_code=204)
def delete_model_variant(
    mid: int,
    variant_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
):
    source = _model_with_variant_relations(db, mid)
    if not source:
        raise HTTPException(404, "Model not found")
    target = _model_with_variant_relations(db, variant_id)
    if not target or _model_group_key(target) != _model_group_key(source):
        raise HTTPException(404, "Variant not found")

    blockers = _model_usage_blockers(db, variant_id)
    if blockers:
        raise HTTPException(409, f"Variant is in use by: {', '.join(blockers)}")

    old_value = {
        "source_model_id": source.id,
        "code": target.code,
        "name": target.name,
        "variant_no": _model_code_parts(target)[1],
    }
    db.query(CollectionModel).filter(CollectionModel.model_id == variant_id).delete(synchronize_session=False)
    db.delete(target)
    log_action(db, current, "delete_variant", "Model", variant_id, new_value=old_value)
    db.commit()


@router.patch("/models/{mid}", response_model=ModelOut)
def update_model(mid: int, payload: ModelIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    m = db.get(Model, mid)
    if not m: raise HTTPException(404, "Model not found")
    update_data = payload.model_dump(exclude_unset=True)
    incoming_details = update_data.get("details_json")
    incoming_general = incoming_details.get("general") if isinstance(incoming_details, dict) else None
    incoming_model_no = _clean_text(
        (incoming_general.get("model_no") or incoming_general.get("modelNo"))
        if isinstance(incoming_general, dict)
        else ""
    )
    if not incoming_model_no and "code" in update_data:
        incoming_model_no, _ = _split_model_code(update_data.get("code"))

    current_model_no, _ = _model_code_parts(m)
    renamed: list[tuple[Model, str]] = []
    if incoming_model_no and _normalized_key(incoming_model_no) != _normalized_key(current_model_no):
        renamed = _rename_model_group(db, m, incoming_model_no)

    for k, v in update_data.items():
        setattr(m, k, v)
    for renamed_model, old_code in renamed:
        if renamed_model.id == m.id:
            continue
        log_action(
            db,
            current,
            "update",
            "Model",
            renamed_model.id,
            old_value={"code": old_code},
            new_value={"code": renamed_model.code, "group_model_no": incoming_model_no},
        )
    source_old_code = next((old_code for row, old_code in renamed if row.id == m.id), m.code)
    log_action(
        db,
        current,
        "update",
        "Model",
        m.id,
        old_value={"code": source_old_code},
        new_value={"code": m.code, "group_model_no": incoming_model_no or current_model_no},
    )
    db.commit(); db.refresh(m)
    return m


@router.post("/models/{mid}/approve", response_model=ModelOut)
def approve_model(mid: int, db: DbSession, current: User = Depends(require_permissions("modeling.approve", "*"))):
    m = db.get(Model, mid)
    if not m: raise HTTPException(404, "Model not found")
    m.status = "approved"
    m.approved_by = current.id
    m.approved_at = datetime.now(timezone.utc)
    log_action(db, current, "approve", "Model", m.id)
    db.commit(); db.refresh(m)
    return m


@router.post("/models/{mid}/images", status_code=201)
def add_image(mid: int, payload: ModelImageIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    if not db.get(Model, mid): raise HTTPException(404, "Model not found")
    data = payload.model_dump()
    data["file_url"] = _validate_file_url(data["file_url"])
    data["image_type"] = _normalize_image_type(data.get("image_type"))
    if data.get("is_primary"):
        db.query(ModelImage).filter(ModelImage.model_id == mid, ModelImage.is_primary.is_(True)).update(
            {"is_primary": False},
            synchronize_session=False,
        )
    img = ModelImage(model_id=mid, **data)
    db.add(img)
    db.flush()
    log_action(db, current, "create", "ModelImage", img.id, new_value={"model_id": mid, "file_url": img.file_url})
    db.commit(); db.refresh(img)
    return {"id": img.id}


@router.post("/models/{mid}/images/upload", status_code=201)
async def upload_image(
    mid: int,
    db: DbSession,
    file: UploadFile = File(...),
    image_type: str | None = Form(None),
    current: User = Depends(require_permissions("modeling.models", "*")),
):
    if not db.get(Model, mid):
        raise HTTPException(404, "Model not found")
    ext = extension_for_upload(file, SAFE_IMAGE_EXTENSIONS | SAFE_DOCUMENT_EXTENSIONS)
    normalized_image_type = _normalize_image_type(image_type)
    os.makedirs(settings.MODEL_FILES_DIR, exist_ok=True)
    safe_name = f"model_{mid}_{uuid4().hex}{ext}"
    abs_path = os.path.join(settings.MODEL_FILES_DIR, safe_name)
    content = await read_validated_upload_content(file, ext, 20 * 1024 * 1024)
    with open(abs_path, "wb") as f:
        f.write(content)
    file_url = f"/storage/model-files/{safe_name}"
    is_primary = normalized_image_type == "model"
    if is_primary:
        db.query(ModelImage).filter(ModelImage.model_id == mid, ModelImage.is_primary.is_(True)).update(
            {"is_primary": False},
            synchronize_session=False,
        )
    img = ModelImage(
        model_id=mid,
        file_url=file_url,
        file_name=file.filename or safe_name,
        content_type=safe_content_type(ext),
        # The file is already persisted in MODEL_FILES_DIR. Keeping another
        # multi-megabyte copy in PostgreSQL makes remote uploads needlessly slow.
        file_data=None,
        image_type=normalized_image_type,
        is_primary=is_primary,
    )
    db.add(img)
    db.flush()
    log_action(db, current, "create", "ModelImage", img.id, new_value={"model_id": mid, "file_url": file_url})
    db.commit()
    return {"id": img.id, "file_url": file_url}


@router.delete("/models/{mid}/images/{image_id}", status_code=204)
def delete_image(
    mid: int,
    image_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
):
    img = db.query(ModelImage).filter(ModelImage.id == image_id, ModelImage.model_id == mid).first()
    if not img:
        raise HTTPException(404, "Pattern file not found")
    file_url = img.file_url
    db.delete(img)
    log_action(db, current, "delete", "ModelImage", image_id, new_value={"model_id": mid, "file_url": file_url})
    db.commit()


@router.post("/models/{mid}/sizes", status_code=201)
def add_size(mid: int, payload: ModelSizeIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    if not db.get(Model, mid): raise HTTPException(404, "Model not found")
    s = ModelSize(model_id=mid, **payload.model_dump())
    db.add(s)
    db.flush()
    log_action(db, current, "create", "ModelSize", s.id, new_value={"model_id": mid, "size": s.size})
    db.commit(); db.refresh(s)
    return {"id": s.id}


@router.delete("/models/{mid}/sizes/{size_id}", status_code=204)
def delete_size(mid: int, size_id: int, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    s = db.query(ModelSize).filter(ModelSize.id == size_id, ModelSize.model_id == mid).first()
    if not s:
        raise HTTPException(404, "Size not found")
    db.delete(s)
    log_action(db, current, "delete", "ModelSize", size_id, new_value={"model_id": mid, "size": s.size})
    db.commit()


@router.post("/models/{mid}/colors", status_code=201)
def add_color(mid: int, payload: ModelColorIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    if not db.get(Model, mid): raise HTTPException(404, "Model not found")
    c = ModelColor(model_id=mid, **payload.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id}


@router.post("/models/{mid}/bom", status_code=201)
def add_bom(mid: int, payload: ModelBOMIn, db: DbSession, current: User = Depends(require_permissions("modeling.bom", "*"))):
    if not db.get(Model, mid): raise HTTPException(404, "Model not found")
    data = _normalize_bom_batch_fields(db, payload.model_dump())
    if data.get("photo_url"):
        data["photo_url"] = _validate_file_url(data["photo_url"])
    b = ModelBOM(model_id=mid, **data)
    db.add(b); db.flush()
    log_action(db, current, "create", "ModelBOM", b.id, new_value={"model_id": mid})
    db.commit(); db.refresh(b)
    return {"id": b.id}


@router.post("/models/{mid}/bom-photo/upload", status_code=201)
async def upload_bom_photo(
    mid: int,
    db: DbSession,
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("modeling.bom", "modeling.models", "*")),
):
    if not db.get(Model, mid):
        raise HTTPException(404, "Model not found")
    content, ext = await read_validated_image_upload(file, 10 * 1024 * 1024)
    os.makedirs(settings.MODEL_FILES_DIR, exist_ok=True)
    safe_name = f"model_bom_{mid}_{uuid4().hex}{ext}"
    abs_path = os.path.join(settings.MODEL_FILES_DIR, safe_name)
    with open(abs_path, "wb") as f:
        f.write(content)
    file_url = f"/storage/model-files/{safe_name}"
    log_action(db, current, "upload", "ModelBOM", mid, new_value={"model_id": mid, "file_url": file_url})
    db.commit()
    return {"file_url": file_url}


@router.patch("/models/{mid}/bom/{bom_id}", status_code=200)
def update_bom(
    mid: int,
    bom_id: int,
    payload: ModelBOMUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.bom", "*")),
):
    b = db.query(ModelBOM).filter(ModelBOM.id == bom_id, ModelBOM.model_id == mid).first()
    if not b:
        raise HTTPException(404, "BOM row not found")
    data = payload.model_dump(exclude_unset=True)
    if "stock_batch_id" in data or "item_id" in data:
        existing = {
            "item_id": b.item_id,
            "stock_batch_id": b.stock_batch_id,
            "color": b.color,
            "photo_url": b.photo_url,
            "unit": b.unit,
        }
        existing.update(data)
        data = _normalize_bom_batch_fields(db, existing)
    if "photo_url" in data and data["photo_url"]:
        data["photo_url"] = _validate_file_url(data["photo_url"])
    for key, value in data.items():
        setattr(b, key, value)
    log_action(db, current, "update", "ModelBOM", b.id, new_value={"model_id": mid, **data})
    db.commit(); db.refresh(b)
    return {"id": b.id}


@router.delete("/models/{mid}/bom/{bom_id}", status_code=204)
def delete_bom(
    mid: int,
    bom_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.bom", "*")),
):
    b = db.query(ModelBOM).filter(ModelBOM.id == bom_id, ModelBOM.model_id == mid).first()
    if not b:
        raise HTTPException(404, "BOM row not found")
    old_value = {
        "model_id": mid,
        "item_id": b.item_id,
        "stock_batch_id": b.stock_batch_id,
        "size": b.size,
        "color": b.color,
    }
    db.delete(b)
    log_action(db, current, "delete", "ModelBOM", bom_id, new_value=old_value)
    db.commit()


@router.delete("/models/{mid}", status_code=204)
def delete_model(mid: int, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    m = db.get(Model, mid)
    if not m:
        raise HTTPException(404, "Model not found")

    blockers: list[str] = []
    if db.query(SalesOrderItem).filter(SalesOrderItem.model_id == mid).first():
        blockers.append("sales orders")
    if db.query(ProductionOrder).filter(ProductionOrder.model_id == mid).first():
        blockers.append("production orders")
    if db.query(ProductionOrderItem).filter(ProductionOrderItem.model_id == mid).first():
        blockers.append("production order items")
    if db.query(Bundle).filter(Bundle.model_id == mid).first():
        blockers.append("bundles")
    if db.query(Package).filter(Package.model_id == mid).first():
        blockers.append("packages")
    if db.query(PackageItem).filter(PackageItem.model_id == mid).first():
        blockers.append("package items")
    if db.query(FinishedGoodsStock).filter(FinishedGoodsStock.model_id == mid).first():
        blockers.append("finished goods stock")
    if blockers:
        raise HTTPException(409, f"Model is in use by: {', '.join(blockers)}")

    db.query(CollectionModel).filter(CollectionModel.model_id == mid).delete(synchronize_session=False)
    db.delete(m)
    log_action(db, current, "delete", "Model", mid, new_value={"code": m.code, "name": m.name})
    db.commit()

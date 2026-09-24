from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import partial
from math import isfinite
import json
import os
from pathlib import Path
import re
from typing import Annotated
from uuid import uuid4
from anyio import CancelScope, to_thread
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi import UploadFile, File, Form
from pydantic import ValidationError
from sqlalchemy import and_, case, func, literal_column, or_, select
from sqlalchemy.orm import Session, lazyload, load_only, selectinload

from app.core.deps import DbSession, CurrentUser, require_permissions, user_permissions
from app.core.config import settings
from app.core.dt import date_filter_bounds
from app.core.model_search import (
    normalized_model_code_column, normalized_model_code_pattern,
    model_search_prefix, model_prefix_number, model_group_prefix_number_column,
)
from app.core.uploads import (
    SAFE_DOCUMENT_EXTENSIONS,
    SAFE_IMAGE_EXTENSIONS,
    UploadCommitState,
    UploadFileWriteState,
    extension_for_upload,
    run_upload_db_work,
    run_upload_file_write,
    safe_content_type,
    read_validated_upload_content,
    upload_processing_slot,
    upload_session_factory,
)
from app.models import (
    Brand, Collection, CollectionModel, Model, ModelImage, ModelSize, ModelColor, ModelBOM, User,
    Item, SalesOrderItem, ProductionOrder, ProductionOrderItem, Bundle, Package, PackageItem, FinishedGoodsStock,
    StockBatch, CuttingRecord,
)
from app.schemas.catalog import (
    BrandIn, BrandOut, BrandPageOut, CollectionIn, CollectionOut, CollectionPageOut,
    CollectionSeasonPageOut,
    ModelIn, ModelOut, ModelDetail, ModelImageIn, ModelImageOut, ModelSizeIn, ModelSizeMeasurements,
    ModelColorIn, ModelBOMIn, ModelBomItemPageOut,
    ModelBOMUpdate, ModelOptionPage, ModelPaidOperationsIn, ModelSellingPriceOut, ModelSummaryOut,
    ModelVariantCreateIn, ModelVariantUpdateIn,
)
from app.schemas.inventory import ItemOut
from app.services.audit import log_action
from app.services.factory_scope import selected_factory_code
from app.services.model_images import model_display_image_url
from app.services.numbering import next_model_variant_no
from app.services.paid_operations import (
    filter_paid_operations_for_factory,
    merge_scoped_paid_operations,
    normalize_paid_operation_factory,
    paid_operations_rows_unchanged,
    paid_operations_from_details,
    sewing_master_factory_scope,
    validate_paid_operations_details_structure,
)
from app.services.stock_batch_policy import validate_stock_batch_unit

router = APIRouter(tags=["catalog"])
COLLECTION_STATUSES = frozenset({"draft", "approved", "archived"})
MODEL_STATUSES = frozenset({"draft", "sample", "approved", "archived"})


def _validate_brand_name_storage_length(name: str) -> None:
    if len(name) > 128:
        raise HTTPException(422, "Brand name cannot exceed 128 characters")


_MODEL_BOM_NUMERIC_FIELDS = {
    "quantity_per_piece": (Decimal("99999999.9999"), Decimal("0.0001")),
    "waste_percent": (Decimal("9999.99"), Decimal("0.01")),
}
_MAX_MODEL_SAM_MINUTES = Decimal("999999.99")
_MODEL_SAM_QUANTUM = Decimal("0.01")
_MODEL_COPY_CODE_BATCH_SIZE = 400
_MODEL_COPY_CODE_MAX_INDEX = 9_999
_MAX_MODEL_DETAILS_JSON_BYTES = 64 * 1024
_MAX_MODEL_DETAILS_JSON_DEPTH = 16


def _validate_model_sam_minutes(data: dict) -> None:
    if "sam_minutes" not in data:
        return
    try:
        value = Decimal(str(data["sam_minutes"]))
        stored_value = value.quantize(_MODEL_SAM_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise HTTPException(422, "sam_minutes exceeds supported precision") from None
    if not value.is_finite():
        raise HTTPException(422, "sam_minutes must be finite")
    if abs(stored_value) > _MAX_MODEL_SAM_MINUTES:
        raise HTTPException(422, "sam_minutes exceeds supported precision")
    data["sam_minutes"] = stored_value


def _standard_catalog_scope() -> str:
    """FastAPI dependency that keeps the shared PLM routes standard-only."""
    return "standard"


def _normalize_catalog_scope(value: str) -> str:
    scope = str(value or "standard").strip().lower()
    if scope not in {"standard", "usluga"}:
        raise HTTPException(400, "Invalid model catalog scope")
    return scope


def _catalog_paid_operation_factory_scope(user: User, catalog_scope: str) -> str | None:
    if _normalize_catalog_scope(catalog_scope) == "usluga":
        return "eco_cotton"
    return _model_paid_operation_factory_scope(user)


_MODEL_COSTING_PERCENT_FIELDS = (
    "labor_pct",
    "electricity_pct",
    "other_pct",
    "target_margin_pct",
)


def _is_finite_json_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _json_values_equal(left: object, right: object) -> bool:
    """Compare JSON-shaped values without recursion or Python's bool/int aliasing."""
    pending = [(left, right)]
    while pending:
        current_left, current_right = pending.pop()
        if type(current_left) is not type(current_right):
            return False
        if isinstance(current_left, dict):
            if current_left.keys() != current_right.keys():
                return False
            pending.extend((current_left[key], current_right[key]) for key in current_left)
        elif isinstance(current_left, list):
            if len(current_left) != len(current_right):
                return False
            pending.extend(zip(current_left, current_right))
        elif current_left != current_right:
            return False
    return True


def _validate_model_details_json_bounds(details: object, *, existing_details: object = None) -> None:
    """Bound changed model-detail documents while keeping exact legacy values editable."""
    if _json_values_equal(details, existing_details):
        return
    if details is None:
        return

    pending = [(details, 0)]
    while pending:
        value, parent_depth = pending.pop()
        if isinstance(value, dict):
            depth = parent_depth + 1
            if depth > _MAX_MODEL_DETAILS_JSON_DEPTH:
                raise HTTPException(
                    422,
                    f"details_json cannot exceed {_MAX_MODEL_DETAILS_JSON_DEPTH} nested container levels",
                )
            if any(not isinstance(key, str) for key in value):
                raise HTTPException(422, "details_json must contain JSON-compatible values")
            pending.extend((child, depth) for child in value.values())
        elif isinstance(value, list):
            depth = parent_depth + 1
            if depth > _MAX_MODEL_DETAILS_JSON_DEPTH:
                raise HTTPException(
                    422,
                    f"details_json cannot exceed {_MAX_MODEL_DETAILS_JSON_DEPTH} nested container levels",
                )
            pending.extend((child, depth) for child in value)
        elif value is not None and type(value) not in (str, bool, int, float):
            raise HTTPException(422, "details_json must contain JSON-compatible values")

    try:
        serialized = json.dumps(
            details,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise HTTPException(422, "details_json must contain finite JSON-compatible values") from None
    if len(serialized) > _MAX_MODEL_DETAILS_JSON_BYTES:
        raise HTTPException(
            422,
            f"details_json cannot exceed {_MAX_MODEL_DETAILS_JSON_BYTES} UTF-8 bytes",
        )


def _validate_model_details_structure(
    details: object,
    *,
    existing_details: object = None,
    unchanged_paid_operations_factory: str | None = None,
) -> None:
    """Check established model-detail containers without constraining legacy keys."""
    if details is None:
        return
    if not isinstance(details, dict):
        raise HTTPException(422, "details_json must be an object")
    validate_paid_operations_details_structure(
        details,
        existing_details=existing_details,
        unchanged_factory=unchanged_paid_operations_factory,
    )
    for key in ("general", "costing"):
        if key in details and not isinstance(details[key], dict):
            raise HTTPException(422, f"details_json.{key} must be an object")
    costing = details.get("costing")
    existing_costing = (
        existing_details.get("costing")
        if isinstance(existing_details, dict)
        and isinstance(existing_details.get("costing"), dict)
        else {}
    )
    if isinstance(costing, dict):
        for key in _MODEL_COSTING_PERCENT_FIELDS:
            if key not in costing:
                continue
            value = costing[key]
            if _is_finite_json_number(value):
                continue
            old_value = existing_costing.get(key)
            if (
                key in existing_costing
                and type(value) is type(old_value)
                and value == old_value
            ):
                continue
            raise HTTPException(422, f"details_json.costing.{key} must be a finite number")

    if "translation" in details:
        translation = details["translation"]
        is_string_map = isinstance(translation, dict) and all(
            isinstance(language, str) and isinstance(value, str)
            for language, value in translation.items()
        )
        if not is_string_map:
            existing_translation = (
                existing_details.get("translation")
                if isinstance(existing_details, dict)
                and "translation" in existing_details
                else None
            )
            unchanged_legacy_translation = (
                isinstance(existing_details, dict)
                and "translation" in existing_details
                and _json_values_equal(translation, existing_translation)
            )
            if not unchanged_legacy_translation:
                raise HTTPException(422, "details_json.translation must be a string-to-string object")


def _model_paid_operation_factory_scope(user: User) -> str | None:
    sewing_scope = sewing_master_factory_scope(user)
    if sewing_scope:
        return sewing_scope
    granted = set(user_permissions(user))
    if "*" not in granted and granted.intersection({"payroll.view", "payroll.manage", "payroll.scan"}):
        return normalize_paid_operation_factory(selected_factory_code(user))
    return None


def _estimate_variant_net_cost_pc(db: DbSession, model: Model) -> float:
    """Estimate per-piece net cost from BOM default costs and costing percentages."""
    item_ids = {int(row.item_id) for row in (model.bom or []) if row.item_id}
    item_cost_map = {
        int(item.id): float(item.default_cost or 0)
        for item in (db.query(Item).filter(Item.id.in_(item_ids)).all() if item_ids else [])
    }
    base_cost = 0.0
    for row in model.bom or []:
        item_cost = item_cost_map.get(int(row.item_id), 0.0) if row.item_id else 0.0
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


def _normalize_model_number(value: object) -> str:
    """Remove the legacy separator for short letter prefixes such as ``TJ-2300``.

    Longer business identifiers such as ``FAMILY-123`` and ``HISTORY-123``
    retain their meaningful separator.
    """
    return re.sub(r"^([^\W\d_]{2})-(?=\d)", r"\1", _clean_text(value), count=1)


def _normalize_model_code(value: object) -> str:
    """Normalize the separator in generated catalog codes.

    Explicit business model numbers are handled separately so their display
    punctuation remains intact.
    """
    return re.sub(r"^([^\W\d_]+)-(?=\d)", r"\1", _clean_text(value), count=1)


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


def _ordered_material_bom_rows(model: Model) -> list[ModelBOM]:
    """Return the model's main material first, with a stable legacy fallback."""
    rows = _material_bom_rows(model)
    main = next(
        (row for row in rows if _normalized_key(getattr(row, "material_role", None)) == "main"),
        None,
    )
    if not main:
        return rows
    return [main, *(row for row in rows if int(row.id or 0) != int(main.id or 0))]


def _primary_material_bom_row(model: Model) -> ModelBOM | None:
    return next(iter(_ordered_material_bom_rows(model)), None)


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


def _parent_variant_fabric(
    db: DbSession,
    model: Model,
    *,
    requested_item_id: int | None = None,
    legacy_stock_batch_id: int | None = None,
    action: str,
) -> tuple[ModelBOM, Item]:
    fabric_row = _primary_material_bom_row(model)
    if not fabric_row:
        raise HTTPException(400, f"Add a fabric BOM row to this model before {action} variants")
    fabric_item = getattr(fabric_row, "item", None) or db.get(Item, int(fabric_row.item_id or 0))
    if not fabric_item:
        raise HTTPException(400, "The parent model fabric type is no longer available")
    if requested_item_id or legacy_stock_batch_id:
        requested_item = _selected_variant_fabric_item(db, requested_item_id, legacy_stock_batch_id)
        if int(requested_item.id) != int(fabric_item.id):
            raise HTTPException(400, "Variant material must match the parent model material")
    return fabric_row, fabric_item


def _variant_fabric_item_id_for_model(model: Model) -> int | None:
    for row in _ordered_material_bom_rows(model):
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
    color_provided: bool = False,
    color: str | None = None,
    picture_url: str | None = None,
) -> None:
    fabric_row = _primary_material_bom_row(model)
    if not fabric_row:
        raise HTTPException(400, "Add a fabric BOM row to this model before editing variants")
    fabric_row.item_id = int(selected_item.id)
    fabric_row.stock_batch_id = None
    if color_provided:
        fabric_row.color = _clean_text(color) or None
    if picture_url is not None:
        fabric_row.photo_url = picture_url
    fabric_row.unit = selected_item.unit or fabric_row.unit


def _fabric_label_for_model(model: Model) -> str:
    for row in _ordered_material_bom_rows(model):
        item = getattr(row, "item", None)
        material_name = _clean_text(getattr(row, "material_name", None))
        item_name = _clean_text(getattr(item, "name", None))
        item_sku = _clean_text(getattr(item, "sku", None))
        color = _clean_text(row.color)
        parts: list[str] = []
        if material_name:
            parts.append(material_name)
        elif item_name:
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
    material_image = _material_model_image(model)
    if material_image:
        return material_image.file_url
    for row in _ordered_material_bom_rows(model):
        item = getattr(row, "item", None)
        picture = row.photo_url or getattr(item, "image_url", None)
        if picture:
            return picture
    primary = _primary_model_image(model)
    if primary:
        return primary.file_url
    return model_display_image_url(model)


def _fabric_picture_url_for_model(model: Model) -> str | None:
    material_image = _material_model_image(model)
    if material_image:
        return material_image.file_url
    for row in _ordered_material_bom_rows(model):
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
    fabric_row = _primary_material_bom_row(model)
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
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
        "color": _clean_text(getattr(fabric_row, "color", None)) or _clean_text(general.get("variant_color")) or None,
        "stock_batch_id": None,
        "selling_price": float(model.selling_price) if model.selling_price is not None else None,
        "selling_price_currency": model.selling_price_currency,
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
        "selling_price": float(model.selling_price) if model.selling_price is not None else None,
        "selling_price_currency": model.selling_price_currency,
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
    base_models = [model for model in ordered_models if not _clean_text(_model_code_parts(model)[1])]
    picture_candidates = base_models + [model for model in ordered_models if model not in base_models]
    for model in picture_candidates:
        model_image = _primary_model_image(model)
        if model_image:
            group_picture = model_image.file_url
            break
    payload.update({
        "status": "approved" if any(model.status == "approved" for model in models) else representative.status,
        "group_key": _model_group_key(representative),
        "group_model_no": group_model_no,
        "group_name": _group_display_name(models),
        "name": _group_display_name(models),
        "variant_count": len(variants),
        "variants": variants,
        "primary_image_url": group_picture or payload.get("primary_image_url"),
    })
    return payload


def _approval_family(db: DbSession, model: Model) -> list[Model]:
    """Approval belongs to one catalog family, including its base row.

    Older families may only have an approved variant. That is existing approval
    evidence, even when their original base row still says Draft.
    """
    if (model.details_json or {}).get("legacy_import") is True:
        return [model]
    key = _model_group_key_from_values(
        model_id=int(model.id or 0), code=model.code, name=model.name,
        general=(model.details_json or {}).get("general"),
    )
    query = db.query(Model).filter(Model.catalog_scope == model.catalog_scope)
    if db.get_bind().dialect.name == "postgresql":
        # Serialize creation and approval, including families with no base row.
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"model-approval:{model.catalog_scope}:{key}"))))
        return query.filter(
            literal_column("models.is_legacy_import").is_(False),
            literal_column("models.model_group_key") == key,
        ).order_by(Model.id).populate_existing().all()
    model_no, _ = _model_code_parts(model)
    candidates = query.filter(
        _model_family_predicate(db, group_key=key, model_no=model_no)
    ).order_by(Model.id).all()
    # Keep the canonical Python identity check as the compatibility boundary;
    # the portable SQL predicate only narrows candidates and must not let code
    # prefixes, wildcard characters, or legacy imports expand the family.
    return [row for row in candidates if _model_group_key(row) == key]


def _model_payload(m: Model, factory_scope: str | None = None) -> dict:
    payload = ModelOut.model_validate(m).model_dump()
    payload["details_json"] = filter_paid_operations_for_factory(payload.get("details_json"), factory_scope)
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


def _models_query(db: DbSession, catalog_scope: str = "standard"):
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
    ).filter(Model.catalog_scope == _normalize_catalog_scope(catalog_scope))


def _variant_models_query(db: DbSession, catalog_scope: str = "standard"):
    """Load only relationships displayed in the bounded variant table."""
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
    ).filter(Model.catalog_scope == _normalize_catalog_scope(catalog_scope))


def _model_thumbnail_subquery():
    preview_image = or_(
        ModelImage.content_type.ilike("image/%"),
        func.lower(ModelImage.file_url).like("%.png"),
        func.lower(ModelImage.file_url).like("%.jpg"),
        func.lower(ModelImage.file_url).like("%.jpeg"),
        func.lower(ModelImage.file_url).like("%.webp"),
        func.lower(ModelImage.file_url).like("%.gif"),
    )
    priority = case(
        (and_(ModelImage.is_primary.is_(True), ModelImage.image_type == "model"), 0),
        (ModelImage.is_primary.is_(True), 1),
        (ModelImage.image_type == "model", 2),
        else_=3,
    )
    return (
        select(ModelImage.file_url)
        .where(ModelImage.model_id == Model.id, preview_image)
        .order_by(priority, ModelImage.id.desc())
        .limit(1)
        .correlate(Model)
        .scalar_subquery()
    )


def _model_summary_query(db: DbSession, catalog_scope: str = "standard"):
    return db.query(
        Model.id,
        Model.code,
        Model.name,
        Model.category,
        Model.brand_id,
        Model.status,
        Model.created_at,
        Model.updated_at,
        _model_thumbnail_subquery().label("thumbnail_url"),
    ).filter(Model.catalog_scope == _normalize_catalog_scope(catalog_scope))


def _catalog_model(db: DbSession, model_id: int, catalog_scope: str = "standard") -> Model | None:
    return db.query(Model).filter(
        Model.id == model_id,
        Model.catalog_scope == _normalize_catalog_scope(catalog_scope),
    ).one_or_none()


def _standard_model(db: DbSession, model_id: int) -> Model | None:
    """Never expose Eco Cotton Usluga identities through shared PLM APIs."""
    return _catalog_model(db, model_id, "standard")


def _model_summary_payload(row) -> dict:
    return ModelSummaryOut(
        id=row.id,
        code=row.code,
        name=row.name,
        category=row.category,
        brand_id=row.brand_id,
        status=row.status,
        thumbnail_url=row.thumbnail_url,
        created_at=row.created_at,
        updated_at=row.updated_at,
    ).model_dump()


def _without_internal_legacy_models(qry):
    """Keep migration-only stock identities out of the PLM catalog."""
    session = getattr(qry, "session", None)
    if session is not None and session.get_bind().dialect.name == "postgresql":
        return qry.filter(literal_column("models.is_legacy_import").is_(False))
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
    catalog_scope: str = "standard",
):
    qry = qry.filter(Model.catalog_scope == _normalize_catalog_scope(catalog_scope))
    if not include_legacy_import:
        qry = _without_internal_legacy_models(qry)
    if status:
        qry = qry.filter(Model.status == status)
    search_query = _clean_text(q)
    if search_query:
        pattern = f"%{search_query}%"
        normalized_code_pattern = normalized_model_code_pattern(search_query)
        qry = qry.filter(
            (Model.name.ilike(pattern))
            | (normalized_model_code_column(Model.code).ilike(normalized_code_pattern))
            | (Model.category.ilike(pattern))
        )
    code_query = _clean_text(code)
    if code_query:
        normalized_code_pattern = normalized_model_code_pattern(code_query)
        qry = qry.filter(normalized_model_code_column(Model.code).ilike(normalized_code_pattern))
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


def _variant_group_predicate(db: DbSession, *, group_key: str, model_no: str):
    general_model_no = func.coalesce(
        Model.details_json["general"]["model_no"].as_string(),
        Model.details_json["general"]["modelNo"].as_string(),
    )
    explicit_variant_no = func.coalesce(
        Model.details_json["general"]["variant_no"].as_string(),
        Model.details_json["general"]["variantNo"].as_string(),
    )
    has_explicit_model_no = func.length(func.trim(func.coalesce(general_model_no, ""))) > 0
    has_explicit_variant_no = func.length(func.trim(func.coalesce(explicit_variant_no, ""))) > 0
    derived_variant = and_(
        ~has_explicit_model_no,
        Model.code.ilike(f"{model_no}-%"),
    )
    is_variant = or_(has_explicit_variant_no, derived_variant)

    if db.get_bind().dialect.name == "postgresql":
        # Migration 0084 materializes this exact family identity and indexes it
        # with model id, so production does an indexed family lookup.
        return and_(
            literal_column("models.is_legacy_import").is_(False),
            literal_column("models.model_group_key") == group_key,
            is_variant,
        )

    # SQLite test databases are built from ORM metadata rather than Alembic and
    # therefore do not have PostgreSQL's generated family columns.
    return and_(
        func.lower(func.trim(func.coalesce(general_model_no, ""))) == _normalized_key(model_no),
        is_variant,
    )


def _model_family_predicate(db: DbSession, *, group_key: str, model_no: str):
    """Select one complete family without treating model text as a LIKE pattern."""
    if db.get_bind().dialect.name == "postgresql":
        return and_(
            literal_column("models.is_legacy_import").is_(False),
            literal_column("models.model_group_key") == group_key,
        )

    general_model_no = func.coalesce(
        Model.details_json["general"]["model_no"].as_string(),
        Model.details_json["general"]["modelNo"].as_string(),
    )
    legacy_flag = Model.details_json["legacy_import"].as_boolean()
    normalized_general = func.lower(func.trim(func.coalesce(general_model_no, "")))
    normalized_model_no = _normalized_key(model_no)
    escaped_prefix = str(model_no).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    normalized_code = func.lower(func.trim(Model.code))
    return and_(
        func.coalesce(legacy_flag, False).is_(False),
        or_(
            normalized_general == normalized_model_no,
            and_(
                normalized_general == "",
                or_(
                    normalized_code == str(model_no).strip().lower(),
                    normalized_code.like(f"{escaped_prefix.lower()}-%", escape="\\"),
                ),
            ),
        ),
    )


def _model_group_members(qry) -> list[list]:
    grouped: dict[str, list] = {}
    for row in qry.order_by(Model.id.desc()).all():
        key = _model_group_key_from_values(
            model_id=int(row.id),
            code=row.code,
            name=row.name,
            general=row.general_details,
        )
        grouped.setdefault(key, []).append(row)
    return list(grouped.values())


def _model_group_member_ids(qry) -> list[list[int]]:
    return [
        [int(row.id) for row in rows]
        for rows in _model_group_members(qry)
    ]


def _model_with_variant_relations(
    db: DbSession,
    mid: int,
    catalog_scope: str = "standard",
    *,
    include_image_binaries: bool = False,
) -> Model | None:
    image_loader = selectinload(Model.images)
    if not include_image_binaries:
        image_loader = image_loader.load_only(
            ModelImage.id,
            ModelImage.model_id,
            ModelImage.file_url,
            ModelImage.file_name,
            ModelImage.content_type,
            ModelImage.image_type,
            ModelImage.is_primary,
            ModelImage.created_at,
        )
    return (
        db.query(Model)
        .options(
            image_loader,
            selectinload(Model.sizes),
            selectinload(Model.colors),
            selectinload(Model.bom).joinedload(ModelBOM.item),
            selectinload(Model.bom).joinedload(ModelBOM.stock_batch),
        )
        .filter(Model.id == mid, Model.catalog_scope == _normalize_catalog_scope(catalog_scope))
        .first()
    )


def _model_usage_blockers(db: DbSession, mid: int) -> list[str]:
    blockers: list[str] = []
    if db.query(SalesOrderItem.id).filter(SalesOrderItem.model_id == mid).first():
        blockers.append("sales orders")
    if db.query(ProductionOrder.id).filter(ProductionOrder.model_id == mid).first():
        blockers.append("production orders")
    if db.query(ProductionOrderItem.id).filter(ProductionOrderItem.model_id == mid).first():
        blockers.append("production order items")
    if db.query(Bundle.id).filter(Bundle.model_id == mid).first():
        blockers.append("bundles")
    if db.query(Package.id).filter(Package.model_id == mid).first():
        blockers.append("packages")
    if db.query(PackageItem.id).filter(PackageItem.model_id == mid).first():
        blockers.append("package items")
    if db.query(FinishedGoodsStock.id).filter(FinishedGoodsStock.model_id == mid).first():
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


def _normalize_bom_fields(db: DbSession, data: dict, catalog_scope: str) -> dict:
    """Keep Usluga fabric descriptions independent from Milana inventory."""
    scope = _normalize_catalog_scope(catalog_scope)
    material_name = _clean_text(data.get("material_name"))
    if material_name:
        if scope != "usluga":
            raise HTTPException(400, "Manual fabric names are available only for Usluga models")
        material_role = _clean_text(data.get("material_role")).lower()
        if material_role not in {"main", "secondary"}:
            raise HTTPException(400, "Choose whether the Usluga fabric is main or secondary")
        data["material_name"] = material_name
        data["material_role"] = material_role
        data["item_id"] = None
        data["stock_batch_id"] = None
        return data

    data["material_name"] = None
    data["material_role"] = None
    normalized = _normalize_bom_batch_fields(db, data)
    if scope == "usluga":
        item = db.get(Item, int(normalized.get("item_id") or 0))
        category = str(getattr(item, "category", "") or "").lower()
        if category in {"fabric", "semi_finished"}:
            raise HTTPException(400, "Enter the Usluga fabric name manually; inventory fabrics are not allowed")
        if category not in {"accessory", "packaging"}:
            raise HTTPException(400, "Usluga inventory links are allowed only for accessories and packaging")
    return normalized


def _validate_bom_numeric_fields(data: dict) -> dict:
    for field, (maximum, quantum) in _MODEL_BOM_NUMERIC_FIELDS.items():
        if field not in data or data[field] is None:
            continue
        try:
            value = Decimal(str(data[field]))
            stored_value = value.quantize(quantum, rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            raise HTTPException(422, f"{field} exceeds supported precision") from None
        if not value.is_finite():
            raise HTTPException(422, f"{field} must be finite")
        if abs(stored_value) > maximum:
            raise HTTPException(422, f"{field} exceeds supported precision")
        data[field] = stored_value
    return data


def _validate_effective_bom_item_unit(
    db: DbSession,
    data: dict,
    *,
    previous: dict | None = None,
) -> None:
    """Validate changed inventory-linked BOM quantities without rewriting legacy rows."""
    item_id = int(data.get("item_id") or 0)
    batch_id = int(data.get("stock_batch_id") or 0)
    unit = data.get("unit")
    current = (item_id or None, batch_id or None, unit)
    if previous is not None and current == (
        previous.get("item_id"), previous.get("stock_batch_id"), previous.get("unit"),
    ):
        return
    if not item_id:
        # Usluga descriptive fabrics intentionally have no inventory item/unit.
        return

    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Inventory master item not found")
    if batch_id:
        batch = db.get(StockBatch, batch_id)
        if not batch:
            raise HTTPException(404, "Stock batch not found")
        if int(batch.item_id) != int(item.id):
            raise HTTPException(400, "Stock batch does not belong to selected item")
        validate_stock_batch_unit(item, batch.unit)
    if unit != item.unit:
        raise HTTPException(409, "BOM unit must match inventory item unit")


def _preflight_copied_bom_item_units(
    db: DbSession,
    rows: list[ModelBOM] | None,
    *,
    replaced_row_ids: set[int] | None = None,
) -> None:
    """Validate inventory-linked BOM rows that a copy will persist unchanged."""
    replaced_row_ids = replaced_row_ids or set()
    for row in rows or []:
        if int(row.id or 0) in replaced_row_ids:
            continue
        item_id = row.item_id
        if not item_id and row.stock_batch_id:
            batch = db.get(StockBatch, row.stock_batch_id)
            if not batch:
                raise HTTPException(404, "Stock batch not found")
            item_id = batch.item_id
        _validate_effective_bom_item_unit(
            db,
            {
                "item_id": item_id,
                "stock_batch_id": row.stock_batch_id,
                "unit": row.unit,
            },
        )


def _ensure_unique_usluga_main_material(
    db: DbSession,
    model_id: int,
    data: dict,
    *,
    exclude_bom_id: int | None = None,
) -> None:
    if data.get("material_role") != "main":
        return
    qry = db.query(ModelBOM.id).filter(
        ModelBOM.model_id == model_id,
        ModelBOM.material_role == "main",
    )
    if exclude_bom_id is not None:
        qry = qry.filter(ModelBOM.id != exclude_bom_id)
    if qry.first():
        raise HTTPException(409, "This Usluga model already has a main fabric; change it to secondary first")


def _split_model_code(code: str | None) -> tuple[str, str]:
    value = str(code or "").strip()
    dash_index = value.rfind("-")
    if 0 < dash_index < len(value) - 1:
        return value[:dash_index], value[dash_index + 1:]
    return value, ""


def _build_model_code(model_no: str, variant_no: str) -> str:
    clean_model_no = _normalize_model_number(model_no)
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


def _rename_model_group(
    db: DbSession,
    source: Model,
    new_model_no: str,
    catalog_scope: str = "standard",
) -> list[tuple[Model, str]]:
    """Rename every variant in source's current group while preserving variant numbers."""
    old_model_no, _ = _model_code_parts(source)
    clean_new_model_no = _clean_text(new_model_no)
    if not old_model_no or not clean_new_model_no:
        raise HTTPException(400, "Model number is required")
    if _normalized_key(old_model_no) == _normalized_key(clean_new_model_no):
        return []

    group_key = _model_group_key(source)
    group_candidates = db.query(Model).options(
        load_only(Model.id, Model.code, Model.name, Model.details_json),
    ).filter(
        Model.catalog_scope == _normalize_catalog_scope(catalog_scope),
        _model_family_predicate(db, group_key=group_key, model_no=old_model_no),
    ).all()
    group = [model for model in group_candidates if _model_group_key(model) == group_key]
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
    normalized_planned_codes = {_normalized_key(next_code) for _, _, next_code in planned}
    external_code_rows = db.query(Model.code).filter(
        ~Model.id.in_(group_ids),
        func.lower(func.trim(Model.code)).in_(normalized_planned_codes),
    ).all()
    external_codes = {_normalized_key(code) for (code,) in external_code_rows}
    for _, variant_no, next_code in planned:
        if _normalized_key(next_code) in external_codes:
            raise HTTPException(
                409,
                f"Model number change conflicts with existing variant {variant_no or next_code}",
            )

    for model, variant_no, _ in planned:
        _validate_model_details_json_bounds(model.details_json)
        details = deepcopy(model.details_json) if isinstance(model.details_json, dict) else {}
        general = details.get("general")
        general = deepcopy(general) if isinstance(general, dict) else {}
        general["model_no"] = clean_new_model_no
        if variant_no:
            general["variant_no"] = variant_no
        else:
            general.pop("variant_no", None)
            general.pop("variantNo", None)
        details["general"] = general
        _validate_model_details_json_bounds(details, existing_details=model.details_json)

    renamed: list[tuple[Model, str]] = []
    for model, variant_no, _ in planned:
        old_code = model.code
        _set_model_identity(model, model_no=clean_new_model_no, variant_no=variant_no)
        renamed.append((model, old_code))
    return renamed


def _model_copy_code(source_code: str, index: int) -> str:
    suffix = "-COPY" if index == 1 else f"-COPY-{index}"
    return f"{source_code[: max(1, 64 - len(suffix))]}{suffix}"


def _unique_model_copy_code(db: DbSession, source_code: str) -> str:
    if db.get_bind().dialect.name == "postgresql":
        # Long source codes can truncate to the same candidate namespace even
        # when their tails differ. Lock the shortest prefix retained by every
        # supported suffix so concurrent clones cannot select the same gap.
        longest_suffix = f"-COPY-{_MODEL_COPY_CODE_MAX_INDEX}"
        namespace = source_code[: max(1, 64 - len(longest_suffix))]
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"model-copy:{namespace}"))))

    # Preserve the historical lowest-gap allocation without a broad LIKE scan
    # or one existence query per occupied code. Exact candidates use the
    # existing unique code index; only the current fixed-size window is loaded.
    for start in range(1, _MODEL_COPY_CODE_MAX_INDEX + 1, _MODEL_COPY_CODE_BATCH_SIZE):
        stop = min(start + _MODEL_COPY_CODE_BATCH_SIZE, _MODEL_COPY_CODE_MAX_INDEX + 1)
        candidates = [_model_copy_code(source_code, index) for index in range(start, stop)]
        existing_codes = {
            code
            for (code,) in db.query(Model.code).filter(Model.code.in_(candidates)).all()
        }
        for candidate in candidates:
            if candidate not in existing_codes:
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
@router.get("/brands", response_model=list[BrandOut] | BrandPageOut)
def list_brands(
    db: DbSession,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    """Return the reference-brand list with a bounded payload."""
    ordered_query = (
        db.query(Brand)
        .options(load_only(Brand.id, Brand.name, Brand.description, Brand.logo_url, Brand.is_active))
        .order_by(Brand.name, Brand.id)
    )
    if page is None and page_size is None:
        return ordered_query.limit(limit).all()
    page = page or 1
    page_size = page_size or 100
    total = ordered_query.order_by(None).count()
    rows = ordered_query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


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
    _validate_brand_name_storage_length(name)
    values = payload.model_dump()
    values["name"] = name
    b = Brand(**values)
    db.add(b); db.flush()
    log_action(db, current, "create", "Brand", b.id)
    db.commit(); db.refresh(b)
    return b


@router.get("/brands/{bid}", response_model=BrandOut)
def get_brand(bid: int, db: DbSession, _: CurrentUser):
    b = (
        db.query(Brand)
        .options(
            load_only(
                Brand.id,
                Brand.name,
                Brand.description,
                Brand.logo_url,
                Brand.is_active,
                raiseload=True,
            )
        )
        .filter(Brand.id == bid)
        .one_or_none()
    )
    if not b: raise HTTPException(404, "Brand not found")
    return b


@router.patch("/brands/{bid}", response_model=BrandOut)
def update_brand(bid: int, payload: BrandIn, db: DbSession, current: User = Depends(require_permissions("modeling.brands", "*"))):
    b = db.get(Brand, bid)
    if not b: raise HTTPException(404, "Brand not found")
    _validate_brand_name_storage_length(payload.name)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    log_action(db, current, "update", "Brand", b.id)
    db.commit(); db.refresh(b)
    return b


# ===== Collections =====
@router.get("/collections", response_model=list[CollectionOut] | CollectionPageOut)
def list_collections(
    db: DbSession,
    _: CurrentUser,
    brand_id: int | None = None,
    page: int | None = None,
    page_size: int | None = None,
    include_total: bool = False,
):
    qry = db.query(Collection).options(
        lazyload("*"),
        load_only(
            Collection.id,
            Collection.brand_id,
            Collection.name,
            Collection.season,
            Collection.year,
            Collection.description,
            Collection.status,
        ),
    )
    if brand_id:
        qry = qry.filter(Collection.brand_id == brand_id)
    paginated = include_total or page is not None or page_size is not None
    if include_total:
        # Preserve the historical include_total contract, which clamps page
        # values rather than rejecting them.
        effective_page = max(1, page or 1)
        effective_page_size = max(1, min(page_size or 50, 500))
    else:
        effective_page = page or 1
        effective_page_size = page_size or 50
        if effective_page < 1 or effective_page_size < 1 or effective_page_size > 500:
            raise HTTPException(422, "page must be >= 1 and page_size must be between 1 and 500")
    total = qry.count() if paginated else 0
    qry = qry.order_by(Collection.id.desc())
    if paginated:
        qry = qry.offset((effective_page - 1) * effective_page_size).limit(effective_page_size)
    rows = [_collection_payload(c) for c in qry.all()]
    if paginated:
        return _pagination_payload(
            rows,
            total=total,
            page=effective_page,
            page_size=effective_page_size,
        )
    return rows


@router.post("/collections", response_model=CollectionOut, status_code=201)
def create_collection(payload: CollectionIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    if not payload.year:
        raise HTTPException(400, "Year is required")
    if payload.status not in COLLECTION_STATUSES:
        raise HTTPException(400, "Invalid collection status")
    c = Collection(**payload.model_dump())
    db.add(c); db.flush()
    log_action(db, current, "create", "Collection", c.id)
    db.commit(); db.refresh(c)
    return c


@router.get("/collections/seasons", response_model=list[str] | CollectionSeasonPageOut)
def list_collection_seasons(
    db: DbSession,
    _: CurrentUser,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    query = (
        db.query(Collection.season)
        .filter(Collection.season.isnot(None), Collection.season != "")
        .group_by(Collection.season)
        .order_by(Collection.season.asc())
    )
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 100
        total = query.order_by(None).count()
        query = query.offset((page - 1) * page_size).limit(page_size)
    rows = [season for (season,) in query.all() if season]
    if total is None:
        return rows
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.get("/collections/{cid}", response_model=CollectionOut)
def get_collection(cid: int, db: DbSession, _: CurrentUser):
    c = db.query(Collection).options(
        load_only(
            Collection.id,
            Collection.brand_id,
            Collection.name,
            Collection.season,
            Collection.year,
            Collection.description,
            Collection.status,
        ),
        lazyload(Collection.brand),
    ).filter(Collection.id == cid).first()
    if not c: raise HTTPException(404, "Collection not found")
    return c


@router.patch("/collections/{cid}", response_model=CollectionOut)
def update_collection(cid: int, payload: CollectionIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    c = db.get(Collection, cid)
    if not c: raise HTTPException(404, "Collection not found")
    data = payload.model_dump(exclude_unset=True)
    if "year" in data and not data["year"]:
        raise HTTPException(400, "Year is required")
    if "status" in data and data["status"] != c.status and data["status"] not in COLLECTION_STATUSES:
        raise HTTPException(400, "Invalid collection status")
    for k, v in data.items():
        setattr(c, k, v)
    log_action(db, current, "update", "Collection", c.id)
    db.commit(); db.refresh(c)
    return c


@router.post("/collections/{cid}/models", status_code=201)
def add_model_to_collection(cid: int, model_id: int, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    if not db.get(Collection, cid):
        raise HTTPException(404, "Collection not found")
    if not _standard_model(db, model_id):
        raise HTTPException(404, "Model not found")
    db.add(CollectionModel(collection_id=cid, model_id=model_id))
    db.commit()
    return {"message": "added"}


# ===== Models =====
@router.get("/model-options", response_model=ModelOptionPage)
def list_model_options(
    db: DbSession,
    _: CurrentUser,
    status: str | None = Query(default=None, max_length=32),
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=50),
    ids: list[int] | None = Query(default=None),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    """Return bounded, relationship-free rows for model selectors."""
    selected_ids = list(dict.fromkeys(ids or []))
    if any(model_id < 1 for model_id in selected_ids) or len(selected_ids) > 50:
        raise HTTPException(422, "ids must contain between 1 and 50 positive model IDs")

    qry = _model_summary_query(db, catalog_scope)
    if selected_ids:
        # An ids-only lookup lets edit forms recover labels that are outside the
        # current search/status page without weakening the normal filters.
        result = (
            qry.filter(Model.id.in_(selected_ids))
            .order_by(Model.created_at.desc(), Model.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size + 1)
            .all()
        )
        has_more = len(result) > page_size
        items = [
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "thumbnail_url": row.thumbnail_url,
            }
            for row in result[:page_size]
        ]
        return {"items": items, "page": page, "page_size": page_size, "has_more": has_more}

    qry = _without_internal_legacy_models(qry)
    status_filter = _clean_text(status)
    if status_filter:
        qry = qry.filter(Model.status == status_filter)
    search_filter = _clean_text(search)
    if search_filter:
        pattern = f"%{search_filter}%"
        normalized_code_pattern = normalized_model_code_pattern(search_filter)
        qry = qry.filter(
            or_(
                Model.name.ilike(pattern),
                normalized_model_code_column(Model.code).ilike(normalized_code_pattern),
            )
        )

    rows = (
        qry.order_by(Model.created_at.desc(), Model.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
        .all()
    )
    has_more = len(rows) > page_size
    items = [
        {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "thumbnail_url": row.thumbnail_url,
        }
        for row in rows[:page_size]
    ]
    return {"items": items, "page": page, "page_size": page_size, "has_more": has_more}


@router.get("/models")
def list_models(
    db: DbSession,
    current: CurrentUser,
    response: Response,
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
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    qry = _apply_model_list_filters(
        _model_summary_query(db, catalog_scope),
        status=status,
        q=q,
        code=code,
        name=name,
        category=category,
        created_from=created_from,
        created_to=created_to,
        include_legacy_import=include_legacy_import,
        catalog_scope=catalog_scope,
    )
    total = None
    if include_total:
        count_qry = _apply_model_list_filters(
            db.query(func.count(Model.id)),
            status=status,
            q=q,
            code=code,
            name=name,
            category=category,
            created_from=created_from,
            created_to=created_to,
            include_legacy_import=include_legacy_import,
            catalog_scope=catalog_scope,
        )
        total = int(count_qry.scalar() or 0)
    result = (
        qry.order_by(Model.created_at.desc(), Model.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
        .all()
    )
    has_more = len(result) > page_size
    rows = [_model_summary_payload(row) for row in result[:page_size]]
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(page_size)
    response.headers["X-Has-More"] = "true" if has_more else "false"
    if total is not None:
        response.headers["X-Total"] = str(total)
    if include_total:
        return {
            "rows": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        }
    return rows


@router.get("/models/variant-groups")
def list_model_variant_groups(
    db: DbSession,
    current: CurrentUser,
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
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    safe_page = max(1, int(page or 1))
    safe_size = max(1, min(int(page_size or 50), 100))
    search_prefix = model_search_prefix(code) or model_search_prefix(q)

    if db.get_bind().dialect.name == "postgresql":
        # Migration 0084 materializes and indexes this family identity. Page
        # those narrow keys first so unrelated details_json values are never
        # hydrated or grouped in Python.
        group_key_column = literal_column("models.model_group_key")
        filtered_keys_qry = db.query(
            group_key_column.label("group_key"),
            func.max(Model.id).label("representative_id"),
        ).select_from(Model)
        filtered_keys_qry = _apply_model_list_filters(
            filtered_keys_qry,
            status=status,
            q=q,
            code=code,
            name=name,
            category=category,
            created_from=created_from,
            created_to=created_to,
            include_legacy_import=include_legacy_import,
            catalog_scope=catalog_scope,
        ).group_by(group_key_column)
        total = filtered_keys_qry.count() if include_total else 0
        group_order = [func.max(Model.id).desc()]
        if search_prefix:
            group_order.insert(0, model_group_prefix_number_column(group_key_column, search_prefix).desc())
        selected_groups = (
            filtered_keys_qry
            .order_by(*group_order)
            .offset((safe_page - 1) * safe_size)
            .limit(safe_size)
            .all()
        )
        selected_keys = [str(row.group_key) for row in selected_groups]
        grouped_ids_by_key: dict[str, list[int]] = {key: [] for key in selected_keys}
        if selected_keys:
            membership_qry = db.query(
                Model.id,
                group_key_column.label("group_key"),
            ).select_from(Model).filter(
                group_key_column.in_(selected_keys),
                Model.catalog_scope == _normalize_catalog_scope(catalog_scope),
            )
            if not include_legacy_import:
                membership_qry = _without_internal_legacy_models(membership_qry)
            for model_id, group_key in membership_qry.order_by(Model.id.desc()).all():
                grouped_ids_by_key[str(group_key)].append(int(model_id))
        grouped_ids = [grouped_ids_by_key[key] for key in selected_keys if grouped_ids_by_key[key]]
    else:
        # SQLite test/dev databases use ORM metadata and do not have the
        # PostgreSQL generated columns. Retain the compatible fallback while
        # bounding the hydrated result page.
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
            catalog_scope=catalog_scope,
        )
        matching_groups = _model_group_members(identity_qry)
        total = len(matching_groups) if include_total else 0
        if search_prefix:
            matching_groups.sort(
                key=lambda rows: (
                    model_prefix_number(_model_code_parts_from_general(rows[0].code, rows[0].general_details)[0], search_prefix),
                    int(rows[0].id),
                ),
                reverse=True,
            )
        matching_groups = matching_groups[(safe_page - 1) * safe_size : safe_page * safe_size]

        has_member_filter = any(
            value is not None and (not isinstance(value, str) or bool(value.strip()))
            for value in (status, q, code, name, category, created_from, created_to)
        )
        if has_member_filter and matching_groups:
            membership_qry = db.query(
                Model.id,
                Model.code,
                Model.name,
                Model.details_json["general"].label("general_details"),
            ).filter(Model.catalog_scope == _normalize_catalog_scope(catalog_scope))
            if not include_legacy_import:
                membership_qry = _without_internal_legacy_models(membership_qry)
            selected_keys = {
                _model_group_key_from_values(
                    model_id=int(rows[0].id),
                    code=rows[0].code,
                    name=rows[0].name,
                    general=rows[0].general_details,
                )
                for rows in matching_groups
                if rows
            }
            full_groups_by_key: dict[str, list] = {}
            for rows in _model_group_members(membership_qry):
                if not rows:
                    continue
                key = _model_group_key_from_values(
                    model_id=int(rows[0].id),
                    code=rows[0].code,
                    name=rows[0].name,
                    general=rows[0].general_details,
                )
                if key in selected_keys:
                    full_groups_by_key[key] = rows
            matching_groups = [
                full_groups_by_key.get(
                    _model_group_key_from_values(
                        model_id=int(rows[0].id),
                        code=rows[0].code,
                        name=rows[0].name,
                        general=rows[0].general_details,
                    ),
                    rows,
                )
                for rows in matching_groups
            ]
        grouped_ids = [[int(row.id) for row in rows] for rows in matching_groups]

    member_ids = [model_id for group_ids in grouped_ids for model_id in group_ids]
    model_loader = _variant_models_query(db, catalog_scope) if compact else _models_query(db, catalog_scope)
    models_by_id = (
        {
            int(model.id): model
            for model in model_loader.filter(Model.id.in_(member_ids)).all()
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
    factory_scope = _catalog_paid_operation_factory_scope(current, catalog_scope)
    if factory_scope and not compact:
        for row in rows:
            row["details_json"] = filter_paid_operations_for_factory(row.get("details_json"), factory_scope)
    if not search_prefix:
        rows.sort(key=lambda row: int(row.get("id") or 0), reverse=True)
    if include_total:
        return _pagination_payload(rows, total=total, page=safe_page, page_size=safe_size)
    return rows


@router.get("/models/bom-items", response_model=list[ItemOut] | ModelBomItemPageOut)
def list_model_bom_items(
    db: DbSession,
    _: User = Depends(require_permissions("modeling.bom", "modeling.models", "*")),
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    """Return only the active item master data needed by the model BOM editor."""
    query = (
        db.query(Item)
        .options(load_only(
            Item.id,
            Item.sku,
            Item.name,
            Item.category,
            Item.unit,
            Item.default_cost,
            Item.reorder_level,
            Item.track_batch,
            Item.is_active,
            Item.image_url,
            Item.composition_json,
        ))
        .filter(
            Item.is_active.is_(True),
            Item.category.in_(("fabric", "semi_finished", "accessory", "packaging")),
        )
    )
    ordered_query = query.order_by(func.lower(Item.name), Item.name, Item.id)
    if page is None and page_size is None:
        return ordered_query.all()

    page = page or 1
    page_size = page_size or 100
    total = query.count()
    rows = ordered_query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.post("/models", response_model=ModelOut, status_code=201)
def create_model(
    payload: ModelIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    catalog_scope = _normalize_catalog_scope(catalog_scope)
    model_data = payload.model_dump()
    details = model_data.get("details_json") if isinstance(model_data.get("details_json"), dict) else {}
    model_data["code"] = (
        _clean_text(model_data.get("code"))
        if details.get("legacy_import") is True
        else _normalize_model_code(model_data.get("code"))
    )
    if db.query(Model).filter(Model.code == model_data["code"]).first():
        raise HTTPException(400, "Model code already exists")
    _validate_model_details_structure(model_data.get("details_json"))
    factory_scope = "eco_cotton" if catalog_scope == "usluga" else sewing_master_factory_scope(current)
    if factory_scope:
        details = merge_scoped_paid_operations({}, details, factory_scope)
    general = details.get("general")
    if not isinstance(general, dict):
        general = {}
    configured_model_no = _normalize_model_number(general.get("model_no") or general.get("modelNo"))
    configured_variant_no = _clean_text(general.get("variant_no") or general.get("variantNo"))
    if configured_model_no:
        general["model_no"] = configured_model_no
        general.pop("modelNo", None)
    if not configured_model_no and not configured_variant_no:
        general["model_no"] = model_data["code"]
    if (configured_model_no or general.get("model_no")) and not configured_variant_no:
        general.pop("variant_no", None)
        general.pop("variantNo", None)
    details["general"] = general
    model_data["details_json"] = details
    _validate_model_sam_minutes(model_data)
    if model_data["status"] not in MODEL_STATUSES:
        raise HTTPException(400, "Invalid model status")
    _validate_model_details_json_bounds(model_data.get("details_json"))

    m = Model(
        **model_data,
        catalog_scope=catalog_scope,
        factory_code="ECO" if catalog_scope == "usluga" else None,
        created_by=current.id,
    )
    if _model_code_parts(m)[1]:
        approval = next((row for row in _approval_family(db, m) if row.status == "approved"), None)
        if approval:
            m.status = "approved"
            m.approved_by = approval.approved_by
            m.approved_at = approval.approved_at
    db.add(m); db.flush()
    log_action(db, current, "create", "Model", m.id, new_value={"code": m.code})
    db.commit(); db.refresh(m)
    return _model_payload(m, factory_scope)


@router.get("/models/{mid}/selling-price", response_model=ModelSellingPriceOut)
def get_model_selling_price(
    mid: int,
    db: DbSession,
    _: CurrentUser,
):
    model = _standard_model(db, mid)
    if not model:
        raise HTTPException(404, "Model not found")
    return {
        "id": model.id,
        "selling_price": float(model.selling_price) if model.selling_price is not None else None,
        "selling_price_currency": model.selling_price_currency,
        "selling_price_source": model.selling_price_source,
        "selling_price_request_id": model.selling_price_request_id,
        "selling_price_updated_at": model.selling_price_updated_at,
    }


@router.get("/models/{mid}/process-qr-sizes")
def get_process_qr_model_sizes(
    mid: int,
    db: DbSession,
    _: CurrentUser,
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    """Resolve manual Process QR sizes without changing editable model rows."""
    model = _catalog_model(db, mid, catalog_scope)
    if not model:
        raise HTTPException(404, "Model not found")

    def cleaned_sizes(rows: list[ModelSize]) -> frozenset[str]:
        return frozenset(value for row in rows if (value := _clean_text(row.size)))

    def result(sizes: frozenset[str], resolution: str) -> dict:
        return {
            "model_id": mid,
            "sizes": sorted(sizes, key=lambda value: (_natural_sort_key(value), value)),
            "resolution": resolution,
        }

    own_sizes = cleaned_sizes(model.sizes)
    if own_sizes:
        return result(own_sizes, "own")
    # Internal import identities cannot borrow sizes from the public family.
    if (model.details_json or {}).get("legacy_import") is True:
        return result(frozenset(), "missing")

    group_key = _model_group_key(model)
    family_query = db.query(Model).options(selectinload(Model.sizes)).filter(
        Model.catalog_scope == model.catalog_scope,
    )
    if db.get_bind().dialect.name == "postgresql":
        # Use the indexed 0084 identity, including base rows, without taking
        # the approval workflow's write-serialization advisory lock.
        family = family_query.filter(
            literal_column("models.is_legacy_import").is_(False),
            literal_column("models.model_group_key") == group_key,
        ).all()
    else:
        # SQLite test metadata has no generated family columns. Use the same
        # canonical identity as catalog grouping, not a code-prefix match.
        family = [
            row for row in family_query.all()
            if (row.details_json or {}).get("legacy_import") is not True
            and _model_group_key(row) == group_key
        ]
    populated_sets = {sizes for row in family if (sizes := cleaned_sizes(row.sizes))}
    if not populated_sets:
        return result(frozenset(), "missing")
    if len(populated_sets) > 1:
        return result(frozenset(), "conflict")
    return result(next(iter(populated_sets)), "inherited")


@router.get("/models/{mid}", response_model=ModelDetail)
def get_model(
    mid: int,
    db: DbSession,
    current: CurrentUser,
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    m = _models_query(db, catalog_scope).filter(Model.id == mid).first()
    if not m: raise HTTPException(404, "Model not found")
    payload = ModelDetail.model_validate(m).model_dump()
    payload["details_json"] = filter_paid_operations_for_factory(
        payload.get("details_json"),
        _catalog_paid_operation_factory_scope(current, catalog_scope),
    )
    return payload


@router.post("/models/{mid}/clone", response_model=ModelOut, status_code=201)
def clone_model(
    mid: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    catalog_scope = _normalize_catalog_scope(catalog_scope)
    source = (
        db.query(Model)
        .options(
            selectinload(Model.images),
            selectinload(Model.sizes),
            selectinload(Model.colors),
            selectinload(Model.bom),
        )
        .filter(Model.id == mid, Model.catalog_scope == catalog_scope)
        .first()
    )
    if not source:
        raise HTTPException(404, "Model not found")

    # Cloning duplicates the effective BOM rows. Check inventory-linked rows
    # before creating the copy so a legacy unit mismatch is not propagated;
    # itemless Usluga description rows remain untouched.
    _preflight_copied_bom_item_units(db, source.bom)
    _validate_model_details_json_bounds(source.details_json)

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
        catalog_scope=catalog_scope,
        factory_code="ECO" if catalog_scope == "usluga" else source.factory_code,
    )
    _validate_model_details_structure(cloned.details_json, existing_details=source.details_json)
    _validate_model_details_json_bounds(cloned.details_json, existing_details=source.details_json)
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
                material_name=row.material_name,
                material_role=row.material_role,
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
    return _model_payload(cloned, _catalog_paid_operation_factory_scope(current, catalog_scope))


@router.get("/models/{mid}/variants")
def list_model_variants(
    mid: int,
    response: Response,
    db: DbSession,
    _: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    """Return fabric variants that belong to the same model group."""
    m = db.query(Model.id, Model.code, Model.name, Model.details_json).filter(
        Model.id == mid,
        Model.catalog_scope == _normalize_catalog_scope(catalog_scope),
    ).first()
    if not m:
        raise HTTPException(404, "Model not found")

    general = (m.details_json or {}).get("general") if isinstance(m.details_json, dict) else {}
    model_no, _ = _model_code_parts_from_general(m.code, general)
    group_key = _model_group_key_from_values(
        model_id=int(m.id),
        code=m.code,
        name=m.name,
        general=general,
    )
    result = (
        _variant_models_query(db, catalog_scope)
        .filter(_variant_group_predicate(db, group_key=group_key, model_no=model_no))
        .order_by(Model.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
        .all()
    )
    response.headers["X-Has-More"] = "true" if len(result) > page_size else "false"
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(page_size)
    return [_model_variant_payload(model) for model in result[:page_size]]


@router.get("/models/{mid}/variants/next-number")
def get_next_model_variant_number(
    mid: int,
    db: DbSession,
    _: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    if not _catalog_model(db, mid, catalog_scope):
        raise HTTPException(404, "Model not found")
    return {"variant_no": next_model_variant_no(db)}


@router.post("/models/{mid}/variants", response_model=ModelOut, status_code=201)
def create_model_variant(
    mid: int,
    payload: ModelVariantCreateIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    catalog_scope = _normalize_catalog_scope(catalog_scope)
    source = _model_with_variant_relations(db, mid, catalog_scope, include_image_binaries=True)
    if not source:
        raise HTTPException(404, "Model not found")

    model_no, _ = _model_code_parts(source)
    model_no = _clean_text(model_no)
    if not model_no:
        raise HTTPException(400, "Model number is required before adding variants")
    requested_variant_no = _clean_text(payload.variant_no)
    variant_no = requested_variant_no or next_model_variant_no(db, reserve=True)

    color = _clean_text(payload.color) or None
    picture_url = _validate_file_url(payload.picture_url) if payload.picture_url else None
    parent_fabric_item: Item | None = None
    if catalog_scope == "standard":
        _, parent_fabric_item = _parent_variant_fabric(
            db,
            source,
            requested_item_id=payload.fabric_item_id,
            legacy_stock_batch_id=payload.stock_batch_id,
            action="creating",
        )
    elif payload.fabric_item_id or payload.stock_batch_id:
        raise HTTPException(400, "Usluga model variants must not select inventory material")
    fabric = _fabric_item_label(parent_fabric_item)

    new_code = f"{model_no}-{variant_no}"
    if db.query(Model.id).filter(Model.code == new_code).first():
        raise HTTPException(400, "Model variant already exists")

    variant_fabric_source = _primary_material_bom_row(source)
    replaced_bom_ids = (
        {int(variant_fabric_source.id)}
        if parent_fabric_item is not None and variant_fabric_source is not None and variant_fabric_source.id
        else set()
    )
    _preflight_copied_bom_item_units(
        db,
        source.bom,
        replaced_row_ids=replaced_bom_ids,
    )

    _validate_model_details_json_bounds(source.details_json)
    details = deepcopy(source.details_json or {})
    general = details.get("general")
    if not isinstance(general, dict):
        general = {}
    general["model_no"] = model_no
    general["variant_no"] = variant_no
    if fabric:
        general["variant_fabric"] = fabric
    else:
        general.pop("variant_fabric", None)
        general.pop("variantFabric", None)
    if parent_fabric_item:
        general["variant_fabric_item_id"] = int(parent_fabric_item.id)
    else:
        general.pop("variant_fabric_item_id", None)
    if color:
        general["variant_color"] = color
    else:
        general.pop("variant_color", None)
    general.pop("variant_stock_batch_id", None)
    details["general"] = general

    _validate_model_details_structure(details, existing_details=source.details_json)
    _validate_model_details_json_bounds(details, existing_details=source.details_json)

    approval = next((row for row in _approval_family(db, source) if row.status == "approved"), None)
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
        status="approved" if approval else "draft",
        created_by=current.id,
        approved_by=approval.approved_by if approval else None,
        approved_at=approval.approved_at if approval else None,
        sam_minutes=source.sam_minutes or 0,
        catalog_scope=catalog_scope,
        factory_code="ECO" if catalog_scope == "usluga" else source.factory_code,
    )
    db.add(cloned)
    db.flush()

    for row in source.sizes or []:
        db.add(ModelSize(model_id=cloned.id, size=row.size, measurement_json=deepcopy(row.measurement_json)))
    for row in source.colors or []:
        db.add(ModelColor(model_id=cloned.id, color_name=row.color_name, color_code=row.color_code))

    for row in source.bom or []:
        is_fabric_row = bool(
            variant_fabric_source
            and int(row.id or 0) == int(variant_fabric_source.id or 0)
        )
        db.add(
            ModelBOM(
                model_id=cloned.id,
                item_id=parent_fabric_item.id if is_fabric_row and parent_fabric_item else row.item_id,
                material_name=None if is_fabric_row and parent_fabric_item else row.material_name,
                material_role=None if is_fabric_row and parent_fabric_item else row.material_role,
                stock_batch_id=None if is_fabric_row else row.stock_batch_id,
                size=row.size,
                color=color if is_fabric_row else row.color,
                photo_url=picture_url if is_fabric_row else row.photo_url,
                quantity_per_piece=row.quantity_per_piece,
                unit=(parent_fabric_item.unit or row.unit) if is_fabric_row and parent_fabric_item else row.unit,
                waste_percent=row.waste_percent,
            )
        )

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
            "fabric_item_id": int(parent_fabric_item.id) if parent_fabric_item else None,
            "fabric": fabric,
            "color": color,
            "picture_url": picture_url,
        },
    )
    db.commit()
    db.refresh(cloned)
    return _model_payload(cloned, _catalog_paid_operation_factory_scope(current, catalog_scope))


@router.patch("/models/{mid}/variants/{variant_id}", response_model=ModelOut)
def update_model_variant(
    mid: int,
    variant_id: int,
    payload: ModelVariantUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    catalog_scope = _normalize_catalog_scope(catalog_scope)
    source = _model_with_variant_relations(db, mid, catalog_scope)
    if not source:
        raise HTTPException(404, "Model not found")
    target = _model_with_variant_relations(db, variant_id, catalog_scope)
    if not target or _model_group_key(target) != _model_group_key(source):
        raise HTTPException(404, "Variant not found")

    model_no, _ = _model_code_parts(source)
    model_no = _clean_text(model_no)
    variant_no = _clean_text(payload.variant_no)
    if not model_no:
        raise HTTPException(400, "Model number is required before editing variants")
    if not variant_no:
        raise HTTPException(400, "Variant number is required")

    source_fabric_row = _primary_material_bom_row(source)
    parent_fabric_item: Item | None = None
    if catalog_scope == "standard" and source_fabric_row:
        source_fabric_row, parent_fabric_item = _parent_variant_fabric(
            db,
            source,
            requested_item_id=payload.fabric_item_id,
            legacy_stock_batch_id=payload.stock_batch_id,
            action="editing",
        )
    elif catalog_scope == "standard" and (payload.fabric_item_id or payload.stock_batch_id):
        raise HTTPException(400, "Add a fabric BOM row to this model before editing variants")
    elif catalog_scope == "usluga" and (payload.fabric_item_id or payload.stock_batch_id):
        raise HTTPException(400, "Usluga model variants must not select inventory material")
    color = _clean_text(payload.color) or None
    picture_url = _validate_file_url(payload.picture_url) if payload.picture_url else None
    fabric = _fabric_item_label(parent_fabric_item) if parent_fabric_item else _details_variant_fabric(target)
    new_code = f"{model_no}-{variant_no}"
    duplicate = db.query(Model.id).filter(Model.code == new_code, Model.id != target.id).first()
    if duplicate:
        raise HTTPException(400, "Model variant already exists")

    old_value = {
        "code": target.code,
        "variant_no": _model_code_parts(target)[1],
        "fabric_item_id": _variant_fabric_item_id_for_model(target),
        "color": getattr(_primary_material_bom_row(target), "color", None),
    }
    _validate_model_details_json_bounds(target.details_json)
    original_details = deepcopy(target.details_json)
    target.code = new_code
    _set_variant_general_details(
        target,
        model_no=model_no,
        variant_no=variant_no,
        fabric_item=parent_fabric_item,
    )
    if catalog_scope == "usluga":
        details = deepcopy(target.details_json or {})
        general = details.get("general") if isinstance(details.get("general"), dict) else {}
        if color:
            general["variant_color"] = color
        else:
            general.pop("variant_color", None)
        details["general"] = general
        target.details_json = details
    _validate_model_details_structure(target.details_json, existing_details=original_details)
    _validate_model_details_json_bounds(target.details_json, existing_details=original_details)
    fabric_row = _primary_material_bom_row(target)
    if fabric_row and parent_fabric_item:
        _apply_variant_fabric_item(
            target,
            parent_fabric_item,
            color_provided=payload.color is not None,
            color=color,
            picture_url=picture_url,
        )
    elif parent_fabric_item and source_fabric_row:
        fabric_row = ModelBOM(
            model_id=target.id,
            item_id=parent_fabric_item.id,
            stock_batch_id=None,
            size=source_fabric_row.size,
            color=color if payload.color is not None else source_fabric_row.color,
            photo_url=picture_url,
            quantity_per_piece=source_fabric_row.quantity_per_piece,
            unit=parent_fabric_item.unit or source_fabric_row.unit,
            waste_percent=source_fabric_row.waste_percent,
        )
        db.add(fabric_row)
    elif fabric_row:
        if payload.color is not None:
            fabric_row.color = color
        if picture_url is not None:
            fabric_row.photo_url = picture_url
    if picture_url is not None:
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
            "fabric_item_id": int(parent_fabric_item.id) if parent_fabric_item else _variant_fabric_item_id_for_model(target),
            "fabric": fabric,
            "color": color,
            "picture_url": picture_url,
        },
    )
    db.commit()
    db.refresh(target)
    return _model_payload(target, _catalog_paid_operation_factory_scope(current, catalog_scope))


@router.delete("/models/{mid}/variants/{variant_id}", status_code=204)
def delete_model_variant(
    mid: int,
    variant_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    source = _model_with_variant_relations(db, mid, catalog_scope)
    if not source:
        raise HTTPException(404, "Model not found")
    target = _model_with_variant_relations(db, variant_id, catalog_scope)
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
def update_model(
    mid: int,
    payload: ModelIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    catalog_scope = _normalize_catalog_scope(catalog_scope)
    m = _catalog_model(db, mid, catalog_scope)
    if not m: raise HTTPException(404, "Model not found")
    update_data = payload.model_dump(exclude_unset=True)
    factory_scope = "eco_cotton" if catalog_scope == "usluga" else sewing_master_factory_scope(current)
    _validate_model_details_structure(
        update_data.get("details_json"),
        existing_details=m.details_json,
        unchanged_paid_operations_factory=factory_scope,
    )
    if (
        "status" in update_data
        and update_data["status"] != m.status
        and update_data["status"] not in MODEL_STATUSES
    ):
        raise HTTPException(400, "Invalid model status")
    unchanged_paid_operations = (
        "details_json" in update_data
        and paid_operations_rows_unchanged(
            update_data["details_json"],
            m.details_json,
            factory=factory_scope,
        )
    )
    if factory_scope and "details_json" in update_data:
        update_data["details_json"] = merge_scoped_paid_operations(
            m.details_json,
            update_data.get("details_json"),
            factory_scope,
        )
    if "details_json" in update_data:
        validate_paid_operations_details_structure(
            update_data["details_json"],
            existing_details=m.details_json,
            allow_oversized_unchanged=unchanged_paid_operations,
        )
        _validate_model_details_json_bounds(update_data["details_json"], existing_details=m.details_json)
    if "code" in update_data:
        update_data["code"] = _normalize_model_number(update_data.get("code"))
    incoming_details = update_data.get("details_json")
    incoming_general = incoming_details.get("general") if isinstance(incoming_details, dict) else None
    incoming_model_no = _normalize_model_number(
        (incoming_general.get("model_no") or incoming_general.get("modelNo"))
        if isinstance(incoming_general, dict)
        else ""
    )
    if isinstance(incoming_general, dict) and incoming_model_no:
        incoming_general["model_no"] = incoming_model_no
        incoming_general.pop("modelNo", None)
    if not incoming_model_no and "code" in update_data:
        incoming_model_no, _ = _split_model_code(update_data.get("code"))

    current_model_no, _ = _model_code_parts(m)
    renamed: list[tuple[Model, str]] = []
    if incoming_model_no and _normalized_key(incoming_model_no) != _normalized_key(current_model_no):
        renamed = _rename_model_group(db, m, incoming_model_no, catalog_scope)

    _validate_model_sam_minutes(update_data)
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
    return _model_payload(m, factory_scope)


@router.patch("/models/{mid}/paid-operations", response_model=ModelOut)
def update_model_paid_operations(
    mid: int,
    payload: ModelPaidOperationsIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    model = _catalog_model(db, mid, catalog_scope)
    if not model:
        raise HTTPException(404, "Model not found")

    factory_scope = _catalog_paid_operation_factory_scope(current, catalog_scope)
    incoming_details = deepcopy(model.details_json) if isinstance(model.details_json, dict) else {}
    incoming_details["paid_operations"] = deepcopy(payload.paid_operations)
    incoming_details.pop("paidOperations", None)
    unchanged_paid_operations = paid_operations_rows_unchanged(
        incoming_details,
        model.details_json,
        factory=factory_scope,
    )
    validate_paid_operations_details_structure(
        incoming_details,
        existing_details=model.details_json,
        unchanged_factory=factory_scope,
    )
    if factory_scope:
        next_details = merge_scoped_paid_operations(model.details_json, incoming_details, factory_scope)
    else:
        next_details = incoming_details

    validate_paid_operations_details_structure(
        next_details,
        existing_details=model.details_json,
        allow_oversized_unchanged=unchanged_paid_operations,
    )
    _validate_model_details_json_bounds(next_details, existing_details=model.details_json)

    old_count = len(paid_operations_from_details(filter_paid_operations_for_factory(model.details_json, factory_scope)))
    model.details_json = next_details
    log_action(
        db,
        current,
        "update_paid_operations",
        "Model",
        model.id,
        old_value={"factory": factory_scope, "operation_count": old_count},
        new_value={"factory": factory_scope, "operation_count": len(payload.paid_operations)},
    )
    db.commit()
    db.refresh(model)
    return _model_payload(model, factory_scope)


@router.post("/models/{mid}/approve", response_model=ModelOut)
def approve_model(
    mid: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.approve", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    m = _catalog_model(db, mid, catalog_scope)
    if not m: raise HTTPException(404, "Model not found")
    family = _approval_family(db, m)
    pending = [row for row in family if row.status != "approved"]
    if _normalize_catalog_scope(catalog_scope) == "usluga":
        pending_ids = [row.id for row in pending]
        main_counts = dict(
            db.query(ModelBOM.model_id, func.count(ModelBOM.id))
            .filter(
                ModelBOM.model_id.in_(pending_ids),
                ModelBOM.material_role == "main",
            )
            .group_by(ModelBOM.model_id)
            .all()
        ) if pending_ids else {}
        if any(main_counts.get(model_id, 0) != 1 for model_id in pending_ids):
            raise HTTPException(409, "Usluga model approval requires exactly one main fabric")
    approved_at = datetime.now(timezone.utc)
    for row in pending:
        row.status = "approved"
        row.approved_by = current.id
        row.approved_at = approved_at
        log_action(db, current, "approve", "Model", row.id,
                   new_value={"approval_scope": "model_family", "requested_model_id": mid})
    db.commit(); db.refresh(m)
    return _model_payload(m, _catalog_paid_operation_factory_scope(current, catalog_scope))


@router.post("/models/{mid}/images", status_code=201)
def add_image(
    mid: int,
    payload: ModelImageIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    if not _catalog_model(db, mid, catalog_scope): raise HTTPException(404, "Model not found")
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


def _write_new_model_document(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with target.open("xb") as stream:
            created = True
            stream.write(content)
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


async def _discard_model_document(target: Path) -> None:
    with CancelScope(shield=True):
        await to_thread.run_sync(target.unlink, True, abandon_on_cancel=False)


def _require_catalog_upload_model(db: Session, model_id: int, catalog_scope: str) -> None:
    if not _catalog_model(db, model_id, catalog_scope):
        raise HTTPException(404, "Model not found")


def _create_uploaded_model_image(
    db: Session,
    *,
    model_id: int,
    catalog_scope: str,
    actor_id: int,
    file_url: str,
    original_name: str,
    stored_content_type: str,
    image_type: str | None,
) -> int:
    _require_catalog_upload_model(db, model_id, catalog_scope)
    actor = db.get(User, actor_id)
    if not actor:
        raise HTTPException(401, "Inactive or unknown user")
    is_primary = image_type == "model"
    if is_primary:
        db.query(ModelImage).filter(
            ModelImage.model_id == model_id,
            ModelImage.is_primary.is_(True),
        ).update({"is_primary": False}, synchronize_session=False)
    image = ModelImage(
        model_id=model_id,
        file_url=file_url,
        file_name=original_name,
        content_type=stored_content_type,
        file_data=None,
        image_type=image_type,
        is_primary=is_primary,
    )
    db.add(image)
    db.flush()
    log_action(
        db,
        actor,
        "create",
        "ModelImage",
        image.id,
        new_value={"model_id": model_id, "file_url": file_url},
    )
    return int(image.id)


def _audit_uploaded_bom_photo(
    db: Session,
    *,
    model_id: int,
    catalog_scope: str,
    actor_id: int,
    file_url: str,
) -> None:
    _require_catalog_upload_model(db, model_id, catalog_scope)
    actor = db.get(User, actor_id)
    if not actor:
        raise HTTPException(401, "Inactive or unknown user")
    log_action(
        db,
        actor,
        "upload",
        "ModelBOM",
        model_id,
        new_value={"model_id": model_id, "file_url": file_url},
    )


@router.post("/models/{mid}/images/upload", status_code=201)
async def upload_image(
    mid: int,
    db: DbSession,
    file: UploadFile = File(...),
    image_type: str | None = Form(None),
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    actor_id = int(current.id)
    worker_sessions = upload_session_factory(db)
    await run_upload_db_work(
        worker_sessions,
        partial(_require_catalog_upload_model, model_id=mid, catalog_scope=catalog_scope),
    )
    ext = extension_for_upload(file, SAFE_IMAGE_EXTENSIONS | SAFE_DOCUMENT_EXTENSIONS)
    normalized_image_type = _normalize_image_type(image_type)
    stored_image = None
    document_target = None
    document_state = UploadFileWriteState()
    commit_state = UploadCommitState()
    try:
        if ext in SAFE_IMAGE_EXTENSIONS:
            from app.services.image_storage import store_uploaded_image

            stored_image = await store_uploaded_image(
                file,
                target_dir=settings.MODEL_FILES_DIR,
                file_url_base="/storage/model-files",
                name_prefix=f"model_{mid}",
                max_bytes=20 * 1024 * 1024,
                prebuild_thumbnails=True,
            )
            safe_name = stored_image.file_name
            file_url = stored_image.file_url
            stored_content_type = stored_image.content_type
        else:
            safe_name = f"model_{mid}_{uuid4().hex}{ext}"
            document_target = Path(settings.MODEL_FILES_DIR) / safe_name
            async with upload_processing_slot():
                content = await read_validated_upload_content(file, ext, 20 * 1024 * 1024)
                await run_upload_file_write(
                    partial(_write_new_model_document, document_target, content),
                    document_state,
                )
            file_url = f"/storage/model-files/{safe_name}"
            stored_content_type = safe_content_type(ext)
        image_id = await run_upload_db_work(
            worker_sessions,
            partial(
                _create_uploaded_model_image,
                model_id=mid,
                catalog_scope=catalog_scope,
                actor_id=actor_id,
                file_url=file_url,
                original_name=file.filename or safe_name,
                stored_content_type=stored_content_type,
                image_type=normalized_image_type,
            ),
            commit=True,
            commit_state=commit_state,
        )
    except BaseException:
        if commit_state.committed:
            raise
        if stored_image is not None:
            from app.services.image_storage import discard_stored_image

            await discard_stored_image(stored_image)
        elif document_state.created and document_target is not None:
            await _discard_model_document(document_target)
        raise
    return {"id": image_id, "file_url": file_url}


@router.delete("/models/{mid}/images/{image_id}", status_code=204)
def delete_image(
    mid: int,
    image_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    if not _catalog_model(db, mid, catalog_scope):
        raise HTTPException(404, "Model not found")
    img = db.query(ModelImage).filter(ModelImage.id == image_id, ModelImage.model_id == mid).first()
    if not img:
        raise HTTPException(404, "Pattern file not found")
    file_url = img.file_url
    db.delete(img)
    log_action(db, current, "delete", "ModelImage", image_id, new_value={"model_id": mid, "file_url": file_url})
    db.commit()


@router.post("/models/{mid}/sizes", status_code=201)
def add_size(
    mid: int,
    payload: ModelSizeIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    if not _catalog_model(db, mid, catalog_scope): raise HTTPException(404, "Model not found")
    if len(payload.size) > 32:
        raise HTTPException(422, "size must be at most 32 characters")
    values = payload.model_dump()
    measurements = values.get("measurement_json")
    if measurements is not None:
        try:
            ModelSizeMeasurements.model_validate(measurements)
        except ValidationError as exc:
            raise RequestValidationError([
                {**error, "loc": ("body", "measurement_json", *error["loc"])}
                for error in exc.errors()
            ]) from exc
    s = ModelSize(model_id=mid, **values)
    db.add(s)
    db.flush()
    log_action(db, current, "create", "ModelSize", s.id, new_value={"model_id": mid, "size": s.size})
    db.commit(); db.refresh(s)
    return {"id": s.id}


@router.delete("/models/{mid}/sizes/{size_id}", status_code=204)
def delete_size(
    mid: int,
    size_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    if not _catalog_model(db, mid, catalog_scope):
        raise HTTPException(404, "Model not found")
    s = db.query(ModelSize).filter(ModelSize.id == size_id, ModelSize.model_id == mid).first()
    if not s:
        raise HTTPException(404, "Size not found")
    db.delete(s)
    log_action(db, current, "delete", "ModelSize", size_id, new_value={"model_id": mid, "size": s.size})
    db.commit()


@router.post("/models/{mid}/colors", status_code=201)
def add_color(
    mid: int,
    payload: ModelColorIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    if not _catalog_model(db, mid, catalog_scope): raise HTTPException(404, "Model not found")
    if len(payload.color_name) > 64:
        raise HTTPException(422, "color_name must be at most 64 characters")
    if payload.color_code is not None and len(payload.color_code) > 16:
        raise HTTPException(422, "color_code must be at most 16 characters")
    c = ModelColor(model_id=mid, **payload.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id}


@router.post("/models/{mid}/bom", status_code=201)
def add_bom(
    mid: int,
    payload: ModelBOMIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.bom", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    if not _catalog_model(db, mid, catalog_scope): raise HTTPException(404, "Model not found")
    data = _normalize_bom_fields(db, payload.model_dump(), catalog_scope)
    _ensure_unique_usluga_main_material(db, mid, data)
    if data.get("photo_url"):
        data["photo_url"] = _validate_file_url(data["photo_url"])
    _validate_bom_numeric_fields(data)
    _validate_effective_bom_item_unit(db, data)
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
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    actor_id = int(current.id)
    worker_sessions = upload_session_factory(db)
    await run_upload_db_work(
        worker_sessions,
        partial(_require_catalog_upload_model, model_id=mid, catalog_scope=catalog_scope),
    )
    from app.services.image_storage import discard_stored_image, store_uploaded_image

    stored = await store_uploaded_image(
        file,
        target_dir=settings.MODEL_FILES_DIR,
        file_url_base="/storage/model-files",
        name_prefix=f"model_bom_{mid}",
        max_bytes=10 * 1024 * 1024,
        prebuild_thumbnails=True,
    )
    file_url = stored.file_url
    commit_state = UploadCommitState()
    try:
        await run_upload_db_work(
            worker_sessions,
            partial(
                _audit_uploaded_bom_photo,
                model_id=mid,
                catalog_scope=catalog_scope,
                actor_id=actor_id,
                file_url=file_url,
            ),
            commit=True,
            commit_state=commit_state,
        )
    except BaseException:
        if not commit_state.committed:
            await discard_stored_image(stored)
        raise
    return {"file_url": file_url}


@router.patch("/models/{mid}/bom/{bom_id}", status_code=200)
def update_bom(
    mid: int,
    bom_id: int,
    payload: ModelBOMUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.bom", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    if not _catalog_model(db, mid, catalog_scope):
        raise HTTPException(404, "Model not found")
    b = db.query(ModelBOM).filter(ModelBOM.id == bom_id, ModelBOM.model_id == mid).first()
    if not b:
        raise HTTPException(404, "BOM row not found")
    data = payload.model_dump(exclude_unset=True)
    identity_fields = {"item_id", "material_name", "material_role", "stock_batch_id"}
    if identity_fields.intersection(data) and db.query(CuttingRecord.id).filter(CuttingRecord.model_bom_id == b.id).first():
        raise HTTPException(409, "Fabric name and role cannot be changed after a cutting batch has used it")
    if "material_name" in data or "material_role" in data:
        existing = {
            "item_id": b.item_id,
            "material_name": b.material_name,
            "material_role": b.material_role,
            "stock_batch_id": b.stock_batch_id,
            "color": b.color,
            "photo_url": b.photo_url,
            "unit": b.unit,
        }
        existing.update(data)
        data = _normalize_bom_fields(db, existing, catalog_scope)
    elif "stock_batch_id" in data or "item_id" in data:
        existing = {
            "item_id": b.item_id,
            "material_name": b.material_name,
            "material_role": b.material_role,
            "stock_batch_id": b.stock_batch_id,
            "color": b.color,
            "photo_url": b.photo_url,
            "unit": b.unit,
        }
        existing.update(data)
        data = _normalize_bom_fields(db, existing, catalog_scope)
    _ensure_unique_usluga_main_material(db, mid, data, exclude_bom_id=b.id)
    if "photo_url" in data and data["photo_url"]:
        data["photo_url"] = _validate_file_url(data["photo_url"])
    _validate_bom_numeric_fields(data)
    effective_data = {
        "item_id": b.item_id,
        "stock_batch_id": b.stock_batch_id,
        "unit": b.unit,
    }
    effective_data.update(data)
    _validate_effective_bom_item_unit(
        db,
        effective_data,
        previous={"item_id": b.item_id, "stock_batch_id": b.stock_batch_id, "unit": b.unit},
    )
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
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    if not _catalog_model(db, mid, catalog_scope):
        raise HTTPException(404, "Model not found")
    b = db.query(ModelBOM).filter(ModelBOM.id == bom_id, ModelBOM.model_id == mid).first()
    if not b:
        raise HTTPException(404, "BOM row not found")
    if db.query(CuttingRecord.id).filter(CuttingRecord.model_bom_id == b.id).first():
        raise HTTPException(409, "Fabric cannot be deleted after a cutting batch has used it")
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
def delete_model(
    mid: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    m = _catalog_model(db, mid, catalog_scope)
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

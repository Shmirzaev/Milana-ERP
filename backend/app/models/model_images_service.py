from __future__ import annotations

import re
from types import SimpleNamespace
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import defer

from app.models import Model, ModelBOM, ModelImage
from app.models.model_identity_service import model_number_fields
from app.models.model_family_images_service import (
    _family_key, _legacy, family_images_for_models, model_family_image, own_model_image,
)


PREVIEW_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
FABRIC_CATEGORIES = {"fabric", "semi_finished"}
MATERIAL_CATEGORIES = {*FABRIC_CATEGORIES, "accessory"}
VARIANT_BOM_CATEGORIES = {*FABRIC_CATEGORIES, ""}


def is_preview_model_image(img: ModelImage) -> bool:
    content_type = str(getattr(img, "content_type", "") or "").lower()
    file_name = str(getattr(img, "file_name", None) or getattr(img, "file_url", "") or "").lower()
    return content_type.startswith("image/") or _looks_like_preview_url(file_name)


def model_print_image_url(model: Model | None) -> str | None:
    if not model:
        return None
    images = sorted((img for img in (model.images or [])
                     if img.image_type == "print" and is_preview_model_image(img)),
                    key=_image_id, reverse=True)
    return images[0].file_url if images else None


def model_preview_image_url(model: Model | None) -> str | None:
    image = model_family_image(model)
    return image.file_url if image else None


def material_preview_image_url(model: Model | None) -> str | None:
    if not model:
        return None

    # A material image attached to the model belongs to that exact variant.
    # Prefer it over BOM/item fallbacks, which may be shared by many variants.
    images = sorted(
        [img for img in (model.images or []) if is_preview_model_image(img)],
        key=_image_id,
        reverse=True,
    )
    typed_material = next((img for img in images if str(img.image_type or "").lower() == "material"), None)
    if typed_material:
        return typed_material.file_url

    bom_rows = sorted(list(model.bom or []), key=_bom_id)
    fabric_rows = [row for row in bom_rows if _bom_item_category(row) in FABRIC_CATEGORIES]
    material_rows = [row for row in bom_rows if _bom_item_category(row) in MATERIAL_CATEGORIES and row not in fabric_rows]
    other_rows = [row for row in bom_rows if row not in fabric_rows and row not in material_rows]
    for row in [*fabric_rows, *material_rows, *other_rows]:
        url = _bom_preview_url(row)
        if url:
            return url

    return None


def model_variant_picture_url(model: Model | None) -> str | None:
    """Return the exact picture used by the Models variant catalog.

    This is deliberately independent of the stock batch assigned to a
    production order. Batch imagery belongs to ``material_image_url`` and must
    not replace the variant thumbnail selected in Models.
    """
    if not model:
        return None

    images = sorted(
        [img for img in (model.images or []) if is_preview_model_image(img)],
        key=_image_id,
        reverse=True,
    )
    typed_material = next(
        (img for img in images if str(img.image_type or "").lower() == "material"),
        None,
    )
    if typed_material:
        # Historical imports/clones can attach another variant's named file.
        # Keep the attachment, but do not display it or silently pick an older
        # picture when its explicit source identity contradicts this variant.
        source_variants = re.findall(
            r"(?<![a-z0-9])(?:v[-_ ]?|variant[-_ ])(\d+)(?![a-z0-9])",
            str(typed_material.file_name or urlsplit(typed_material.file_url or "").path.rsplit("/", 1)[-1]),
            flags=re.IGNORECASE,
        )
        if source_variants:
            variant = model_number_fields(model)["variant_no"] or ""
            match = re.fullmatch(r"(?:v[-_ ]?)?(\d+)", variant, flags=re.IGNORECASE)
            if match and any(int(source) != int(match[1]) for source in source_variants):
                return None
        return typed_material.file_url

    # Garment/print pictures belong in their own columns. A missing variant
    # photo must not borrow a family garment or shared BOM/item/batch picture.
    return None


def model_display_image_url(model: Model | None) -> str | None:
    return model_preview_image_url(model)


def warehouse_stock_image_url(model: Model | None) -> str | None:
    """Return the picture shown for a finished-goods warehouse model.

    Legacy stock can have a sticker evidence photo even when it intentionally
    has no catalogue model or material image.  That evidence is a warehouse
    fallback only: it must not make the hidden legacy row appear as a normal
    Models/Variants catalogue image.
    """
    display_url = model_display_image_url(model)
    if display_url or not model:
        return display_url
    return _warehouse_evidence_image_url(model)


def _warehouse_evidence_image_url(model) -> str | None:
    warehouse_images = sorted(
        [
            img
            for img in (model.images or [])
            if is_preview_model_image(img)
            and str(img.image_type or "").lower() == "warehouse_package"
        ],
        key=_image_id,
        reverse=True,
    )
    return warehouse_images[0].file_url if warehouse_images else None


def warehouse_stock_image_urls(db, model_ids) -> dict[int, str | None]:
    """Resolve warehouse pictures without hydrating full model technical data."""
    ids = sorted(set(model_ids))
    models = {}
    legacy = Model.details_json["legacy_import"]
    if db.get_bind().dialect.name == "sqlite":
        legacy = func.json_type(Model.details_json, "$.legacy_import") == "true"
    for offset in range(0, len(ids), 400):
        chunk = ids[offset:offset + 400]
        for row in db.execute(select(
            Model.id, Model.code, Model.name, Model.catalog_scope, Model.factory_code,
            Model.details_json["general"].label("identity_general"),
            legacy.label("identity_legacy"),
        ).where(Model.id.in_(chunk))):
            models[row.id] = SimpleNamespace(
                id=row.id, code=row.code, name=row.name, catalog_scope=row.catalog_scope,
                factory_code=row.factory_code,
                details_json={"general": row.identity_general, "legacy_import": row.identity_legacy},
                images=[],
            )
        for image in db.scalars(select(ModelImage).where(ModelImage.model_id.in_(chunk)).options(
            defer(ModelImage.file_data, raiseload=True),
        )):
            models[image.model_id].images.append(image)
    families = family_images_for_models(db, models.values())
    result = {}
    for mid, model in models.items():
        image = own_model_image(model) if _legacy(model) else families.get(_family_key(model))
        result[mid] = image.file_url if image else _warehouse_evidence_image_url(model)
    return result


def _bom_preview_url(row: ModelBOM) -> str | None:
    for value in (
        row.photo_url,
        getattr(getattr(row, "stock_batch", None), "image_url", None),
        getattr(getattr(row, "item", None), "image_url", None),
    ):
        if value and _looks_like_preview_url(str(value)):
            return str(value)
    return None


def _bom_item_category(row: ModelBOM) -> str:
    return str(getattr(getattr(row, "item", None), "category", "") or "").lower()


def _looks_like_preview_url(value: str) -> bool:
    trimmed = str(value or "").strip()
    if not trimmed:
        return False
    if trimmed.startswith("/storage/model-files/"):
        return True
    path = urlsplit(trimmed).path or trimmed
    return path.lower().endswith(PREVIEW_EXTENSIONS)


def _image_id(img: ModelImage) -> int:
    try:
        return int(getattr(img, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _bom_id(row: ModelBOM) -> int:
    try:
        return int(getattr(row, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0

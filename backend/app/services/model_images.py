from __future__ import annotations

from urllib.parse import urlsplit

from app.models import Model, ModelBOM, ModelImage


PREVIEW_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
FABRIC_CATEGORIES = {"fabric", "semi_finished"}
MATERIAL_CATEGORIES = {*FABRIC_CATEGORIES, "accessory"}
VARIANT_BOM_CATEGORIES = {*FABRIC_CATEGORIES, ""}


def is_preview_model_image(img: ModelImage) -> bool:
    content_type = str(getattr(img, "content_type", "") or "").lower()
    file_name = str(getattr(img, "file_name", None) or getattr(img, "file_url", "") or "").lower()
    return content_type.startswith("image/") or _looks_like_preview_url(file_name)


def model_preview_image_url(model: Model | None) -> str | None:
    if not model:
        return None
    images = sorted(
        [img for img in (model.images or []) if is_preview_model_image(img)],
        key=_image_id,
        reverse=True,
    )
    model_images = [
        img
        for img in images
        if str(img.image_type or "").lower() in {"", "model"}
    ]
    primary = (
        next((img for img in model_images if img.is_primary and str(img.image_type or "").lower() == "model"), None)
        or next((img for img in model_images if img.is_primary), None)
        or next((img for img in model_images if str(img.image_type or "").lower() == "model"), None)
        or (model_images[0] if model_images else None)
    )
    return primary.file_url if primary else None


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
        return typed_material.file_url

    bom_rows = sorted(
        [
            row
            for row in (model.bom or [])
            if _bom_item_category(row) in VARIANT_BOM_CATEGORIES
        ],
        key=_bom_id,
    )
    for row in bom_rows:
        for value in (
            row.photo_url,
            getattr(getattr(row, "item", None), "image_url", None),
        ):
            if value:
                return str(value)

    catalog_primary = (
        next(
            (
                img
                for img in images
                if img.is_primary and str(img.image_type or "").lower() == "model"
            ),
            None,
        )
        or next((img for img in images if img.is_primary), None)
        or next(
            (img for img in images if str(img.image_type or "").lower() == "model"),
            None,
        )
        or (images[0] if images else None)
    )
    if catalog_primary:
        return catalog_primary.file_url

    return material_preview_image_url(model)


def model_display_image_url(model: Model | None) -> str | None:
    return model_preview_image_url(model) or material_preview_image_url(model)


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

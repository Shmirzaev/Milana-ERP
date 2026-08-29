from __future__ import annotations

import base64
import mimetypes
import os

from app.core.config import settings
from app.models import Model, ModelBOM, ModelImage


PREVIEW_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
FABRIC_CATEGORIES = {"fabric", "semi_finished"}
MATERIAL_CATEGORIES = {*FABRIC_CATEGORIES, "accessory"}


def is_preview_model_image(img: ModelImage) -> bool:
    content_type = str(img.content_type or "").lower()
    file_name = str(img.file_name or img.file_url or "").lower()
    return content_type.startswith("image/") or file_name.endswith(PREVIEW_EXTENSIONS)


def _image_data_uri(content: bytes, content_type: str | None) -> str:
    safe_type = (content_type or "image/png").strip() or "image/png"
    if not safe_type.lower().startswith("image/"):
        safe_type = "image/png"
    return f"data:{safe_type};base64," + base64.b64encode(content).decode("ascii")


def _uploaded_file_data_uri(file_url: str | None, content_type: str | None = None, file_data: bytes | None = None) -> str | None:
    value = str(file_url or "").strip()
    if not value:
        return None
    if file_data:
        return _image_data_uri(bytes(file_data), content_type)
    if not value.startswith("/storage/model-files/"):
        return value if value.startswith(("https://", "http://")) else None

    name = value.rsplit("/", 1)[-1]
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    path = os.path.realpath(os.path.join(settings.MODEL_FILES_DIR, name))
    root = os.path.realpath(settings.MODEL_FILES_DIR)
    if not (path == root or path.startswith(root + os.sep)) or not os.path.isfile(path):
        return None
    guessed_type = content_type or mimetypes.guess_type(name)[0] or "image/png"
    with open(path, "rb") as fh:
        return _image_data_uri(fh.read(), guessed_type)


def _model_image_src(img: ModelImage | None) -> str | None:
    if not img or not is_preview_model_image(img):
        return None
    return _uploaded_file_data_uri(img.file_url, img.content_type, img.file_data)


def _bom_image_src(row: ModelBOM) -> str | None:
    if row.photo_url:
        src = _uploaded_file_data_uri(row.photo_url)
        if src:
            return src
    stock_batch = getattr(row, "stock_batch", None)
    if stock_batch and getattr(stock_batch, "image_url", None):
        src = _uploaded_file_data_uri(stock_batch.image_url)
        if src:
            return src
    item = getattr(row, "item", None)
    if item and getattr(item, "image_url", None):
        return _uploaded_file_data_uri(item.image_url)
    return None


def material_label_image_src(model: Model | None) -> str | None:
    """Best printable picture for bundle/package QR labels.

    Prefer the exact model-variant material image, then BOM fallbacks, then a
    normal model preview so printed labels still have a useful visual cue.
    """
    if not model:
        return None

    images = sorted(
        [img for img in (model.images or []) if is_preview_model_image(img)],
        key=lambda img: int(getattr(img, "id", 0) or 0),
        reverse=True,
    )
    typed_material = next((img for img in images if str(img.image_type or "").lower() == "material"), None)
    src = _model_image_src(typed_material)
    if src:
        return src

    bom_rows = list(model.bom or [])
    fabric_rows = [row for row in bom_rows if _bom_item_category(row) in FABRIC_CATEGORIES]
    material_rows = [row for row in bom_rows if _bom_item_category(row) in MATERIAL_CATEGORIES and row not in fabric_rows]
    other_rows = [row for row in bom_rows if row not in fabric_rows and row not in material_rows]
    for row in [*fabric_rows, *material_rows, *other_rows]:
        src = _bom_image_src(row)
        if src:
            return src

    typed_model = next((img for img in images if str(img.image_type or "").lower() == "model"), None)
    primary = next((img for img in images if img.is_primary), None)
    return _model_image_src(typed_model or primary or (images[0] if images else None))


def fabric_label_image_src(model: Model | None) -> str | None:
    """Printable fabric picture without falling back to the garment photo."""
    if not model:
        return None

    images = sorted(
        [img for img in (model.images or []) if is_preview_model_image(img)],
        key=lambda img: int(getattr(img, "id", 0) or 0),
        reverse=True,
    )
    typed_material = next((img for img in images if str(img.image_type or "").lower() == "material"), None)
    src = _model_image_src(typed_material)
    if src:
        return src

    for row in model.bom or []:
        if _bom_item_category(row) not in FABRIC_CATEGORIES:
            continue
        src = _bom_image_src(row)
        if src:
            return src

    return None


def model_label_image_src(model: Model | None) -> str | None:
    """Best printable model photo, embedded when it is stored locally."""
    if not model:
        return None

    images = [img for img in (model.images or []) if is_preview_model_image(img)]
    typed_model = next((img for img in images if str(img.image_type or "").lower() == "model"), None)
    primary = next((img for img in images if img.is_primary), None)
    return _model_image_src(typed_model or primary or (images[0] if images else None))


def variant_label_image_src(model: Model | None) -> str | None:
    """Printable picture for the selected model variant."""
    return model_label_image_src(model)


def _bom_item_category(row: ModelBOM) -> str:
    return str(getattr(getattr(row, "item", None), "category", "") or "").lower()

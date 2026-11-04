"""Read-only artwork selection for an already-authorized production order."""
from app.core.signing import sign_path
from app.core.uploads import SAFE_DOCUMENT_EXTENSIONS, SAFE_IMAGE_EXTENSIONS
from app.schemas import Model


def _is_image(path: str, content_type: str | None) -> bool:
    if not path:
        return False
    bare_path = path.split("?", 1)[0].split("#", 1)[0].lower()
    if bare_path.endswith(tuple(SAFE_DOCUMENT_EXTENSIONS)):
        return False
    mime = str(content_type or "").lower().strip()
    # Explicit document MIME wins over a misleading image filename.
    return mime.startswith("image/") or (
        mime in ("", "application/octet-stream")
        and bare_path.endswith(tuple(SAFE_IMAGE_EXTENSIONS))
    )


def floor_print_image_url(model: Model | None, attachments: list[dict] | None) -> str | None:
    """Order artwork first, then the exact model variant's print image.

    Callers supply the linked sales order's attachments, falling back to the
    production order when that list is empty, just like the Printing board.
    Never borrow artwork from another order or a model-family sibling.
    """
    for attachment in attachments or []:
        if not isinstance(attachment, dict):
            continue
        path = str(attachment.get("file_url") or "").strip()
        if _is_image(path, attachment.get("content_type")):
            return sign_path(path)
    # Keep the shared catalog selector unchanged. Floor previews must skip
    # newer document attachments rather than hide an older valid print image.
    images = sorted(
        (image for image in (model.images or []) if image.image_type == "print") if model else [],
        key=lambda image: image.id or 0,
        reverse=True,
    )
    for image in images:
        if _is_image(str(image.file_url or "").strip(), image.content_type):
            # Model files already use their existing public/read URL; signing
            # here would change its storage semantics or discard query params.
            return image.file_url
    return None

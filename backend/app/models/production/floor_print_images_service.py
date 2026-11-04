"""Read-only artwork selection for an already-authorized production order."""
from app.core.signing import sign_path
from app.core.uploads import SAFE_DOCUMENT_EXTENSIONS, SAFE_IMAGE_EXTENSIONS
from app.models.model_images_service import model_print_image_url
from app.schemas import Model


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
        if not path:
            continue
        content_type = str(attachment.get("content_type") or "").lower().strip()
        bare_path = path.split("?", 1)[0].split("#", 1)[0].lower()
        if bare_path.endswith(tuple(SAFE_DOCUMENT_EXTENSIONS)):
            continue
        extension_image = bare_path.endswith(tuple(SAFE_IMAGE_EXTENSIONS))
        # An explicit document MIME must not become a picture just because its
        # original filename happens to end in an image extension.
        if content_type.startswith("image/") or (content_type in ("", "application/octet-stream") and extension_image):
            return sign_path(path)
    return model_print_image_url(model)

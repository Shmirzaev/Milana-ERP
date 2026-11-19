"""Mapped writes for variant PATCH, using the service's existing session."""
from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import Model, ModelBOM, ModelImage


def set_variant_code(model: Model, code: str) -> None:
    model.code = code


def set_variant_details(model: Model, details: dict) -> None:
    model.details_json = details


def set_fabric_item(row: ModelBOM, *, item_id: int, unit: str | None,
                    color_provided: bool, color: str | None, picture_url: str | None) -> None:
    row.item_id = item_id
    row.stock_batch_id = None
    if color_provided:
        row.color = color
    if picture_url is not None:
        row.photo_url = picture_url
    row.unit = unit


def add_fabric_row(db: Session, *, model_id: int, item_id: int,
                   size: str | None, color: str | None, photo_url: str | None,
                   quantity_per_piece, unit: str | None, waste_percent) -> ModelBOM:
    row = ModelBOM(model_id=model_id, item_id=item_id, stock_batch_id=None,
                   size=size, color=color, photo_url=photo_url,
                   quantity_per_piece=quantity_per_piece, unit=unit, waste_percent=waste_percent)
    db.add(row)
    return row


def set_fabric_display(row: ModelBOM, *, color_provided: bool,
                       color: str | None, picture_url: str | None) -> None:
    if color_provided:
        row.color = color
    if picture_url is not None:
        row.photo_url = picture_url


def save_image(db: Session, *, model_id: int, image: ModelImage | None,
               image_type: str, picture_url: str, file_name: str | None,
               content_type: str | None) -> None:
    if image is not None:
        image.file_url = picture_url
        image.file_name = file_name
        image.content_type = content_type
        image.file_data = None
        image.is_primary = False
    else:
        db.add(ModelImage(model_id=model_id, file_url=picture_url, file_name=file_name,
                          content_type=content_type, image_type=image_type, is_primary=False))


def delete_print_images(db: Session, images: list[ModelImage]) -> None:
    for image in images:
        db.delete(image)

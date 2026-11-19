"""Mapped variant creation writes using the service-owned transaction."""
from sqlalchemy.orm import Session

from app.libs.types.catalog import VariantBomValues, VariantCreateValues
from app.schemas.catalog.catalog import CollectionModel, Model, ModelBOM, ModelImage, ModelSize


def insert_variant(db: Session, values: VariantCreateValues) -> Model:
    fields = dict(values)
    fields["catalog_scope"] = values["catalog_scope"].value
    row = Model(**fields)
    db.add(row)
    db.flush()
    return row


def copy_size(db: Session, model_id: int, size: str, measurement_json: dict | None) -> None:
    db.add(ModelSize(model_id=model_id, size=size, measurement_json=measurement_json))


def copy_bom(db: Session, values: VariantBomValues) -> None:
    db.add(ModelBOM(**values))


def copy_pattern(db: Session, model_id: int, file_url: str, file_name: str | None,
                 content_type: str | None, file_data: bytes | None) -> None:
    db.add(ModelImage(model_id=model_id, file_url=file_url, file_name=file_name,
                      content_type=content_type, file_data=file_data,
                      image_type="pattern", is_primary=False))


def copy_collection_link(db: Session, *, collection_id: int, model_id: int) -> None:
    db.add(CollectionModel(collection_id=collection_id, model_id=model_id))

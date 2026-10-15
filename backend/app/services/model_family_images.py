"""One scoped garment-photo selection for catalog, workflow and print views."""
from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import and_, event, func, inspect, literal_column, select
from sqlalchemy.orm import Session, defer, object_session

from app.models import Model, ModelImage
from app.services.model_identity import model_number_fields


_CACHE = "model_family_photos"
_IDENTITY_FIELDS = {"id", "code", "name", "details_json", "catalog_scope", "factory_code"}


def _family_key(model) -> tuple[str | None, str | None, str]:
    number = model_number_fields(model)["model_no"]
    value = number or model.name
    key = ("model:" if number else "name:") + " ".join(str(value).casefold().split()) if value else f"id:{model.id}"
    return model.catalog_scope, model.factory_code, key


def _legacy(model) -> bool:
    return isinstance(model.details_json, dict) and model.details_json.get("legacy_import") is True


def own_model_image(model) -> ModelImage | None:
    # Import locally to keep the public image helpers free of an import cycle.
    from app.services.model_images import is_preview_model_image

    images = sorted(
        (image for image in model.images or []
         if str(image.image_type or "").lower() in {"", "model"} and is_preview_model_image(image)),
        key=lambda image: int(image.id or 0), reverse=True,
    )
    return next((image for image in images if image.is_primary), None) or next(iter(images), None)


def family_image_from_members(model, members) -> ModelImage | None:
    """Prefer the newest base record's garment, then the newest family garment."""
    if _legacy(model):
        return own_model_image(model)
    family = [member for member in members if not _legacy(member) and _family_key(member) == _family_key(model)]
    bases = [member for member in family if not model_number_fields(member)["variant_no"]]
    base = max(bases, key=lambda member: int(member.id or 0), default=None)
    image = own_model_image(base) if base else None
    if image:
        return image
    return max(
        (image for member in family if (image := own_model_image(member)) is not None),
        key=lambda image: int(image.id or 0), default=None,
    )


@event.listens_for(Session, "after_flush")
def _invalidate_family_photos(session, _context):
    if any(isinstance(row, (Model, ModelImage)) for row in (*session.new, *session.dirty, *session.deleted)):
        session.info.pop(_CACHE, None)


def model_family_image(model: Model | None) -> ModelImage | None:
    if model is None:
        return None
    state = inspect(model, raiseerr=False)
    db = object_session(model) if state is not None else None
    if db is None or not state.persistent or _legacy(model):
        return own_model_image(model)
    if db.autoflush:
        db.flush()
    transaction, cache = db.info.get(_CACHE, (None, {}))
    key = _family_key(model)
    if transaction is db.get_transaction() and key in cache:
        return cache[key]

    # Resolve every already-loaded page model together, using the indexed family
    # key. Cache only within this transaction; never cache across requests/users.
    models = [row for row in db.identity_map.values()
              if isinstance(row, Model) and _IDENTITY_FIELDS.issubset(row.__dict__)
              and not _legacy(row)]
    return family_images_for_models(db, [model, *models])[_family_key(model)]


def family_images_for_models(db: Session, models) -> dict:
    """Batch metadata-only lookup for loaded models or scalar catalog rows."""
    if db.autoflush:
        db.flush()
    transaction, cache = db.info.get(_CACHE, (None, {}))
    if transaction is not db.get_transaction():
        cache = {}
    keys = {_family_key(row) for row in models if not _legacy(row)} - cache.keys()
    if keys:
        grouped_keys = defaultdict(list)
        for scope, factory, group in keys:
            grouped_keys[scope, factory].append(group)
        members = defaultdict(list)
        for (scope, factory), groups in grouped_keys.items():
            for offset in range(0, len(groups), 400):
                chunk = set(groups[offset:offset + 400])
                statement = select(
                    Model.id, Model.code, Model.name, Model.details_json,
                    Model.catalog_scope, Model.factory_code, ModelImage,
                ).select_from(Model).outerjoin(ModelImage, and_(
                    ModelImage.model_id == Model.id,
                    func.lower(func.coalesce(ModelImage.image_type, "")).in_(("", "model")),
                )).where(Model.catalog_scope == scope, Model.factory_code == factory).options(
                    defer(ModelImage.file_data, raiseload=True),
                )
                if db.get_bind().dialect.name == "postgresql":
                    statement = statement.where(
                        literal_column("models.is_legacy_import").is_(False),
                        literal_column("models.model_group_key").in_(chunk),
                    )
                by_id = {}
                for row in db.execute(statement):
                    member = by_id.setdefault(row.id, SimpleNamespace(
                        id=row.id, code=row.code, name=row.name, details_json=row.details_json,
                        catalog_scope=row.catalog_scope, factory_code=row.factory_code, images=[],
                    ))
                    if row.ModelImage is not None:
                        member.images.append(row.ModelImage)
                for member in by_id.values():
                    member_key = _family_key(member)
                    if not _legacy(member) and member_key[2] in chunk:
                        members[member_key].append(member)
        for family_key in keys:
            family = members[family_key]
            cache[family_key] = family_image_from_members(family[0], family) if family else None
        db.info[_CACHE] = (db.get_transaction(), cache)
    return cache

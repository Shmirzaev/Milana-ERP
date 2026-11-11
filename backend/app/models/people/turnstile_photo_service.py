from __future__ import annotations

import hashlib
import os
import warnings
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from anyio import to_thread
from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.uploads import read_validated_image_upload
from app.libs.dto.people.turnstile_output import GatePhotoOutput
from app.libs.enums.turnstile import GateMode, GatePhotoValidation
from app.models.factory_scope_service import selected_factory_code
from app.models.image_storage_service import upload_processing_slot
from app.models.people.turnstile_access_service import authorize_gate_actor, authorize_gate_employee
from app.schemas import User
from app.schemas.people.turnstile import GatePhotoAsset
from app.schemas.people.turnstile_persistence import insert_photo_asset


def _enabled() -> None:
    if settings.TURNSTILE_PROVISIONING_MODE is GateMode.DISABLED or (settings.strict_security_required and settings.TURNSTILE_PROVISIONING_MODE is GateMode.SIMULATOR):
        raise HTTPException(403, "Turnstile provisioning is disabled")


def _normalize(content: bytes) -> tuple[bytes, int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format not in {"JPEG", "PNG"}:
                    raise HTTPException(400, "Unsupported image")
                if image.width * image.height > settings.TURNSTILE_PHOTO_MAX_PIXELS:
                    raise HTTPException(400, "Image dimensions exceed limit")
                image.load()
                oriented = ImageOps.exif_transpose(image)
                rgb = oriented.convert("RGB")
                output = BytesIO()
                rgb.save(output, format="JPEG", quality=90, optimize=False)
                return output.getvalue(), rgb.width, rgb.height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(400, "Invalid image") from exc


async def upload_photo(db: Session, actor: User, employee_id: int, upload: UploadFile) -> GatePhotoOutput:
    _enabled()
    authorize_gate_employee(db, actor, employee_id)
    factory = selected_factory_code(actor)
    async with upload_processing_slot():
        content, ext = await read_validated_image_upload(upload, settings.TURNSTILE_PHOTO_MAX_BYTES)
        if ext not in {".jpg", ".png"}:
            raise HTTPException(400, "Unsupported image")
        jpeg, width, height = await to_thread.run_sync(_normalize, content)
        root = Path(settings.TURNSTILE_PHOTOS_DIR).resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        name = f"{uuid4().hex}.jpg"
        path = root / name
        created = False
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(fd, "wb") as stream:
                stream.write(jpeg)
            asset = insert_photo_asset(db, employee_id=employee_id, factory_code=factory,
                created_by=actor.id, stored_name=name, sha256=hashlib.sha256(jpeg).hexdigest(),
                width=width, height=height, content_type="image/jpeg",
                validation=GatePhotoValidation.TECHNICAL_VALIDATED)
            result = GatePhotoOutput.model_validate(asset)
        except BaseException:
            db.rollback()
            if created:
                path.unlink(missing_ok=True)
            raise
        # A failed commit may have reached the database. Preserve the asset on
        # an uncertain outcome so a durable row can never point to a deleted file.
        db.commit()
        return result


def read_photo(db: Session, actor: User, asset_id: int) -> Path:
    _enabled()
    authorize_gate_actor(actor)
    asset = db.get(GatePhotoAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "Photo not found")
    authorize_gate_employee(db, actor, asset.employee_id)
    if asset.factory_code != selected_factory_code(actor):
        raise HTTPException(404, "Photo not found")
    root = Path(settings.TURNSTILE_PHOTOS_DIR).resolve()
    name = asset.stored_name
    if not isinstance(name, str) or len(name) != 36 or not name.endswith(".jpg") or any(c not in "0123456789abcdef" for c in name[:32]):
        raise HTTPException(404, "Photo not found")
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "Photo not found")
    return path

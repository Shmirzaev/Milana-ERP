"""SEC04-only fixture and readback; runs inside the disposable backend container."""

import json
import os
from pathlib import Path
import sys

from PIL import Image, ImageDraw
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.schemas import Model, ModelImage, Role, User


EMAIL = "sec04-viewer@example.com"
MODEL_CODE = "SEC04-VERIFY-001"
FILE_NAME = "sec04-verification.png"
FILE_URL = f"/storage/model-files/{FILE_NAME}"


def require_local_stack() -> None:
    url = make_url(settings.DATABASE_URL)
    if not (
        os.environ.get("SEC04_LOCAL_STACK") == "1"
        and url.drivername == "postgresql+psycopg2"
        and url.host == "db" and url.database == "sec04" and url.username == "sec04"
        and settings.MODEL_FILES_DIR == "/app/storage/model_files"
        and settings.shared_store_url == "sqlite:////app/storage/shared-store.db"
    ):
        raise RuntimeError("SEC04 fixture requires the disposable local Compose stack")


def setup() -> None:
    password = os.environ["SEC04_VIEWER_PASSWORD"]
    target = Path(settings.MODEL_FILES_DIR) / FILE_NAME
    with SessionLocal() as db:
        if (db.query(User).filter_by(email=EMAIL).first()
                or db.query(Model).filter_by(code=MODEL_CODE).first() or target.exists()):
            raise RuntimeError("SEC04 fixture already exists; reset the local stack to repeat")
        role = Role(name="SEC04 Local Viewer", permissions=["modeling.models"])
        db.add(role)
        db.flush()
        user = User(name="SEC04 Viewer", email=EMAIL, password_hash=hash_password(password),
                    role_id=role.id, factory_code="MIL", extra_permissions=[], is_active=True)
        db.add(user)
        db.flush()
        model = Model(code=MODEL_CODE, name="SEC04 Verification Model", category="t-shirt",
                      status="approved", created_by=user.id)
        db.add(model)
        db.flush()
        db.add(ModelImage(model_id=model.id, file_url=FILE_URL, file_name=FILE_NAME,
                          content_type="image/png", image_type="model", is_primary=True))
        target.parent.mkdir(parents=True, exist_ok=True)
        picture = Image.new("RGB", (160, 160), "#183a76")
        ImageDraw.Draw(picture).rectangle((24, 24, 136, 136), fill="#f5c542")
        try:
            picture.save(target)
            db.commit()
        except Exception:
            target.unlink(missing_ok=True)
            raise
    print(json.dumps({"fixture": "created", "user": EMAIL, "model": MODEL_CODE,
                      "file_url": FILE_URL, "thumbnail_url": f"/storage/model-files/thumb/{FILE_NAME}?size=160"}))


def revoke() -> None:
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=EMAIL).one()
        if not user.is_active:
            raise RuntimeError("SEC04 viewer is already revoked")
        user.is_active = False
        db.commit()
    print(json.dumps({"user": EMAIL, "is_active": False}))


def readback() -> None:
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=EMAIL).one()
        model = db.query(Model).filter_by(code=MODEL_CODE).one()
        images = db.query(ModelImage).filter_by(model_id=model.id, file_url=FILE_URL).count()
        connections = db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = 'sec04' AND backend_type = 'client backend'")).scalar_one()
    print(json.dumps({"user": EMAIL, "is_active": user.is_active,
                      "model": MODEL_CODE, "image_records": images,
                      "file_exists": (Path(settings.MODEL_FILES_DIR) / FILE_NAME).is_file(),
                      "postgres_connections": connections}))


if __name__ == "__main__":
    require_local_stack()
    {"fixture": setup, "revoke": revoke, "readback": readback}[sys.argv[1]]()

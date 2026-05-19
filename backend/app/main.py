import os
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api.router import api_router
from app.db.session import engine
from app.db.base import Base
from app.db import schema_hotfix
import app.models  # noqa: F401 — register models with metadata

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("milana")

app = FastAPI(title=settings.APP_NAME, version="0.1.0")


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """Catch-all so a programming bug returns proper JSON instead of crashing
    the worker. HTTPException continues to be handled by FastAPI normally."""
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {type(exc).__name__}"},
    )


@app.on_event("startup")
def _on_startup() -> None:
    """Bring the DB schema up to date with the codebase.

    Runs in this order:
      1. `create_all` — adds any brand-new TABLE that doesn't exist yet.
      2. `schema_hotfix.run` — adds any new COLUMN to existing tables via
         idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

    This makes the backend self-migrating on Render's free tier where we have
    no Shell access. Safe to run on every boot.
    """
    try:
        Base.metadata.create_all(bind=engine)
        log.info("startup: create_all complete")
    except Exception as e:
        log.exception("startup: create_all failed: %s", e)
    try:
        schema_hotfix.run(engine)
    except Exception as e:
        log.exception("startup: schema_hotfix failed: %s", e)
    # Best-effort: run the seed so new roles/permissions/sewing-flows propagate
    # on every restart. The seed is idempotent (insert-if-missing) and
    # permission-refreshing.
    # Keep web startup fast in hosted environments (Render health checks can
    # fail if heavy seed tasks run before the server binds to $PORT).
    # Set RUN_SEED_ON_STARTUP=true explicitly where auto-seed is desired.
    if os.environ.get("RUN_SEED_ON_STARTUP", "false").lower() == "true":
        try:
            from app.db.seed import seed as _seed
            _seed()
        except Exception as e:
            log.exception("startup: seed failed: %s", e)

cors_origins = settings.cors_origins_list
allow_all_cors = "*" in cors_origins
safe_default_origins = [
    "http://localhost:3000",
    "https://milanaerp-frontend.onrender.com",
]
merged_cors_origins: list[str] = []
for origin in [*safe_default_origins, *cors_origins]:
    o = origin.strip().rstrip("/")
    if o and o not in merged_cors_origins:
        merged_cors_origins.append(o)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all_cors else merged_cors_origins,
    # We use Bearer tokens, not cookies. For wildcard CORS we must disable
    # credentials, otherwise browsers reject cross-origin requests.
    allow_credentials=not allow_all_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Serve generated QR/barcode images
os.makedirs(settings.BARCODE_STORAGE_DIR, exist_ok=True)
app.mount("/storage/barcodes", StaticFiles(directory=settings.BARCODE_STORAGE_DIR), name="barcodes")
os.makedirs(settings.MODEL_FILES_DIR, exist_ok=True)
app.mount("/storage/model-files", StaticFiles(directory=settings.MODEL_FILES_DIR), name="model-files")
os.makedirs(settings.SALES_ORDER_FILES_DIR, exist_ok=True)
app.mount("/storage/sales-order-files", StaticFiles(directory=settings.SALES_ORDER_FILES_DIR), name="sales-order-files")


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}

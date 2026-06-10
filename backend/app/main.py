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


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
    )
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # Uploaded files under /storage are served unauthenticated (so <img> tags can
    # render them with bearer-token auth). They have unguessable UUID names; keep
    # them out of shared caches and search indexes to limit URL-leak exposure.
    if request.url.path.startswith("/storage/"):
        response.headers.setdefault("Cache-Control", "private, no-store")
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    return response


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """Catch-all so a programming bug returns proper JSON instead of crashing
    the worker. HTTPException continues to be handled by FastAPI normally."""
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.on_event("startup")
def _on_startup() -> None:
    """Bring the DB schema up to date with the codebase.

    Runs in this order:
      1. `create_all` — adds any brand-new TABLE that doesn't exist yet.
      2. `schema_hotfix.run` — adds any new COLUMN to existing tables via
         idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

    This makes the backend self-migrating in hosted environments where we do
    not have interactive Shell access. Safe to run on every boot.
    """
    settings.validate_runtime_security()
    # In production validate_runtime_security() hard-fails on insecure defaults.
    # Outside production we don't block local dev, but we still surface them
    # loudly so a misconfigured deploy (e.g. ENV left at "development") can't run
    # on the default JWT secret silently.
    if not settings.is_production:
        if settings.JWT_SECRET.strip() in {"", "dev-secret", "test-secret"} or len(settings.JWT_SECRET.strip()) < 32:
            log.warning("SECURITY: JWT_SECRET is a weak/default value. Set a unique 32+ char secret before exposing this instance.")
        if "://erp:erp@" in settings.DATABASE_URL:
            log.warning("SECURITY: DATABASE_URL uses default development credentials.")
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
    # Keep web startup fast in hosted environments; health checks can fail if
    # heavy seed tasks run before the server binds to $PORT.
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
    "https://milana-erp-web.vercel.app",
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

# Sales-order printing attachments may contain customer-supplied design files, so
# they are NOT served from a public static mount. Access requires a short-lived
# signed URL (see app.core.signing); the API hands those out in serialized
# responses. Path is validated to stay within the storage root.
os.makedirs(settings.SALES_ORDER_FILES_DIR, exist_ok=True)
_SALES_ORDER_FILES_ROOT = os.path.realpath(settings.SALES_ORDER_FILES_DIR)


@app.get("/storage/sales-order-files/{name}")
def serve_sales_order_file(name: str, exp: str | None = None, sig: str | None = None):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from app.core.signing import verify_path

    bare_path = f"/storage/sales-order-files/{name}"
    if not verify_path(bare_path, exp, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired link")
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=404, detail="Not found")
    abs_path = os.path.realpath(os.path.join(_SALES_ORDER_FILES_ROOT, name))
    if not (abs_path == _SALES_ORDER_FILES_ROOT or abs_path.startswith(_SALES_ORDER_FILES_ROOT + os.sep)):
        raise HTTPException(status_code=404, detail="Not found")
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(abs_path)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}

import os
import logging
from time import perf_counter
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response

from app.core.config import settings
from app.core.deps import DbSession
from app.core.security import decode_token
from app.core.shared_store import get_shared_counter_store
from app.api.router import api_router
from app.db.session import SessionLocal, engine
import app.models  # noqa: F401 — register models with metadata

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("milana")


def _alembic_config() -> AlembicConfig:
    here = Path(__file__).resolve()
    for root in (here.parents[1], here.parents[2]):
        candidate = root / "alembic.ini"
        if candidate.exists():
            return AlembicConfig(str(candidate))
    raise RuntimeError("Could not locate alembic.ini for startup migration verification")


def _verify_alembic_current() -> None:
    """Ensure production is running against an Alembic-migrated database."""
    config = _alembic_config()
    script = ScriptDirectory.from_config(config)
    expected_heads = set(script.get_heads())
    with engine.connect() as conn:
        current_heads = set(MigrationContext.configure(conn).get_current_heads())
    if current_heads != expected_heads:
        current = ", ".join(sorted(current_heads)) or "<none>"
        expected = ", ".join(sorted(expected_heads)) or "<none>"
        raise RuntimeError(
            "Database schema is not at the required Alembic head. "
            f"current={current}; expected={expected}. Run `alembic upgrade head` before starting the app."
        )
    log.info("startup: database migration head verified (%s)", ", ".join(sorted(expected_heads)))


def _run_local_schema_sync() -> None:
    """Local/dev-only schema bootstrap for disposable databases."""
    if settings.strict_security_required:
        raise RuntimeError("STARTUP_SCHEMA_SYNC cannot be enabled for production or public deployments")
    from app.db.base import Base
    from app.db import schema_hotfix

    Base.metadata.create_all(bind=engine)
    log.info("startup: dev schema create_all complete")
    schema_hotfix.run(engine)


def _run_startup() -> None:
    """Validate runtime settings and database readiness before serving."""
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
    if settings.STARTUP_SCHEMA_SYNC:
        _run_local_schema_sync()
    elif settings.strict_security_required:
        try:
            _verify_alembic_current()
        except Exception as e:
            log.exception("startup: database migration check failed: %s", e)
            raise
    else:
        log.info("startup: schema sync disabled; run Alembic migrations or set STARTUP_SCHEMA_SYNC=true for local bootstrap.")
    # Best-effort: run the seed so new roles/permissions/sewing-flows propagate
    # on every restart. The seed is idempotent (insert-if-missing) and
    # permission-refreshing.
    # Keep web startup fast in hosted environments; health checks can fail if
    # heavy seed tasks run before the server binds to $PORT.
    # Set RUN_SEED_ON_STARTUP=true explicitly where auto-seed is desired.
    if os.environ.get("RUN_SEED_ON_STARTUP", "false").lower() == "true":
        try:
            from app.db.seed import seed as _seed
            _seed(ensure_schema=False)
        except Exception as e:
            log.exception("startup: seed failed: %s", e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _run_startup()
    yield


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_RATE_LIMIT_EXEMPT_PATHS = {"/health"}


def _rate_limit_client_key(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    # In supported deployments the app sits behind a trusted proxy. This keeps
    # direct clients from picking arbitrary buckets in normal operation while
    # still separating users behind Vercel/HF proxies and local TestClient.
    trusted_peer = peer in {"testclient", "127.0.0.1", "::1", "localhost"}
    if not trusted_peer:
        try:
            import ipaddress
            peer_ip = ipaddress.ip_address(peer)
            trusted_peer = peer_ip.is_private or peer_ip.is_loopback
        except ValueError:
            trusted_peer = False
    if trusted_peer and forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return peer


def _rate_limit_allowed(key: str) -> tuple[bool, int | None]:
    if not settings.GLOBAL_RATE_LIMIT_ENABLED:
        return True, None
    limit = int(settings.GLOBAL_RATE_LIMIT_PER_MINUTE or 0)
    window = int(settings.GLOBAL_RATE_LIMIT_WINDOW_SECONDS or 60)
    if limit <= 0 or window <= 0:
        return False, window if window > 0 else 60

    store = get_shared_counter_store()
    store_key = f"global-rate:{key}"
    count = store.increment(store_key, window)
    if count > limit:
        return False, store.ttl(store_key) or window
    return True, None


def _origin_from_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except Exception:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _trusted_csrf_origins(request: Request) -> set[str]:
    configured = {o.strip().rstrip("/").lower() for o in settings.cors_origins_list if o.strip() and o.strip() != "*"}
    configured.update({
        "http://localhost:3000",
        "https://erp.milanapremium.uz",
        "https://milana-erp-web.vercel.app",
    })
    host = request.headers.get("host", "").strip().lower()
    if host:
        configured.add(f"{request.url.scheme}://{host}")
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if proto in {"http", "https"}:
            configured.add(f"{proto}://{host}")
    return configured


def _request_origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    source = origin or referer
    if not source:
        # Non-browser/API clients do not send Origin/Referer. They still need a
        # valid bearer token or auth cookie at the route dependency layer.
        return True
    source_origin = _origin_from_url(source)
    return bool(source_origin and source_origin in _trusted_csrf_origins(request))


@app.middleware("http")
async def _global_rate_limit(request: Request, call_next):
    if request.method.upper() != "OPTIONS" and request.url.path not in _RATE_LIMIT_EXEMPT_PATHS:
        allowed, retry_after = _rate_limit_allowed(_rate_limit_client_key(request))
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Try again later."},
                headers={"Retry-After": str(retry_after or 60)},
            )
    return await call_next(request)


@app.middleware("http")
async def _csrf_origin_guard(request: Request, call_next):
    if request.method.upper() in _UNSAFE_METHODS and not _request_origin_allowed(request):
        return JSONResponse(status_code=403, content={"detail": "Untrusted request origin"})
    return await call_next(request)


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
        if request.url.path.startswith("/storage/model-files/thumb/"):
            response.headers.setdefault("Cache-Control", "private, max-age=604800")
        elif request.url.path.startswith("/storage/model-files/"):
            response.headers.setdefault("Cache-Control", "private, max-age=86400")
        else:
            response.headers.setdefault("Cache-Control", "private, no-store")
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    return response


@app.middleware("http")
async def _request_timing(request: Request, call_next):
    started = perf_counter()
    response = await call_next(request)
    duration_ms = (perf_counter() - started) * 1000
    response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
    if duration_ms >= 1000:
        log.warning(
            "slow_request method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
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


cors_origins = settings.cors_origins_list
safe_default_origins = [
    "http://localhost:3000",
    "https://erp.milanapremium.uz",
    "https://milana-erp-web.vercel.app",
]
merged_cors_origins: list[str] = []
for origin in [*safe_default_origins, *cors_origins]:
    o = origin.strip().rstrip("/")
    if o == "*":
        log.warning("Ignoring wildcard CORS origin; credentialed ERP API requests require explicit trusted origins.")
        continue
    if o and o not in merged_cors_origins:
        merged_cors_origins.append(o)

app.add_middleware(
    CORSMiddleware,
    allow_origins=merged_cors_origins,
    # Auth is cookie-backed, so CORS must never reflect arbitrary origins with
    # credentials. Add each trusted frontend origin explicitly.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Most authenticated ERP list endpoints return highly compressible JSON. Keep
# the threshold above small control responses so compression CPU is spent only
# where it materially reduces transfer size. Static model images are already
# encoded and are therefore unaffected by this middleware.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

app.include_router(api_router)

# Serve generated QR/barcode images
os.makedirs(settings.BARCODE_STORAGE_DIR, exist_ok=True)
app.mount("/storage/barcodes", StaticFiles(directory=settings.BARCODE_STORAGE_DIR), name="barcodes")
os.makedirs(settings.MODEL_FILES_DIR, exist_ok=True)
_MODEL_FILES_ROOT = os.path.realpath(settings.MODEL_FILES_DIR)
_MODEL_THUMBS_ROOT = os.path.realpath(os.path.join(settings.MODEL_FILES_DIR, "_thumbs"))


def _model_file_path_if_exists(name: str):
    from fastapi import HTTPException

    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=404, detail="Not found")
    abs_path = os.path.realpath(os.path.join(_MODEL_FILES_ROOT, name))
    if not (abs_path == _MODEL_FILES_ROOT or abs_path.startswith(_MODEL_FILES_ROOT + os.sep)):
        raise HTTPException(status_code=404, detail="Not found")
    return abs_path if os.path.isfile(abs_path) else None


def _safe_model_file_path(name: str):
    from fastapi import HTTPException

    abs_path = _model_file_path_if_exists(name)
    if not abs_path:
        raise HTTPException(status_code=404, detail="Not found")
    return abs_path


def _model_image_record(name: str, db: DbSession):
    from app.models import ModelImage

    file_url = f"/storage/model-files/{name}"
    return (
        db.query(ModelImage)
        .filter(ModelImage.file_url == file_url, ModelImage.file_data.isnot(None))
        .order_by(ModelImage.id.desc())
        .first()
    )


def _require_model_file_token(request: Request) -> None:
    """Validate image access without checking out a database connection.

    A model list can render hundreds of thumbnails at once. Using CurrentUser
    here made every image reserve a database connection merely to re-check the
    same signed JWT, which could exhaust the pool and block login/API requests.
    """
    from fastapi import HTTPException, status

    authorization = request.headers.get("authorization", "").strip()
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not token:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME, "").strip()
    try:
        payload = decode_token(token) if token else None
        user_id = int((payload or {}).get("sub") or 0)
        if user_id <= 0:
            raise ValueError("missing subject")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


@app.get("/storage/model-files/{name}")
def serve_model_file(name: str, request: Request):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    _require_model_file_token(request)
    abs_path = _model_file_path_if_exists(name)
    if abs_path:
        return FileResponse(abs_path)

    with SessionLocal() as db:
        img = _model_image_record(name, db)
        file_data = bytes(img.file_data) if img and img.file_data else b""
        content_type = img.content_type if img else None
    if not file_data:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=file_data,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=604800"},
    )


@app.get("/storage/model-files/thumb/{name}")
def serve_model_thumbnail(name: str, request: Request, size: int = 320):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from PIL import UnidentifiedImageError

    _require_model_file_token(request)
    source_path = _model_file_path_if_exists(name)
    image_data = b""
    if not source_path:
        with SessionLocal() as db:
            image_record = _model_image_record(name, db)
            image_data = bytes(image_record.file_data) if image_record and image_record.file_data else b""
    if not source_path and not image_data:
        raise HTTPException(status_code=404, detail="Not found")

    safe_size = max(96, min(int(size or 320), 1280))
    os.makedirs(_MODEL_THUMBS_ROOT, exist_ok=True)
    thumb_name = f"{safe_size}_{name}.webp"
    thumb_path = os.path.realpath(os.path.join(_MODEL_THUMBS_ROOT, thumb_name))
    if not thumb_path.startswith(_MODEL_THUMBS_ROOT + os.sep):
        raise HTTPException(status_code=404, detail="Not found")

    source_mtime = os.path.getmtime(source_path) if source_path else 0
    if not os.path.isfile(thumb_path) or os.path.getmtime(thumb_path) < source_mtime:
        try:
            from app.services.image_storage import ensure_webp_thumbnail

            ensure_webp_thumbnail(
                destination_path=thumb_path,
                size=safe_size,
                source_path=source_path,
                image_data=image_data,
            )
        except (UnidentifiedImageError, OSError, HTTPException):
            raise HTTPException(status_code=415, detail="File is not a previewable image")

    return FileResponse(
        thumb_path,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=604800"},
    )

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

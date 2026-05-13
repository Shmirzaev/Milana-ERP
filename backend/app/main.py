import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.router import api_router

app = FastAPI(title=settings.APP_NAME, version="0.1.0")

cors_origins = settings.cors_origins_list
allow_all_cors = "*" in cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all_cors else cors_origins,
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


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}

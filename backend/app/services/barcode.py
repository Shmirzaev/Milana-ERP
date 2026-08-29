"""QR code and barcode generation utilities.

Stores PNG files on the local filesystem under settings.BARCODE_STORAGE_DIR and
returns a URL path served by FastAPI (mounted at /storage/barcodes).
"""
from __future__ import annotations
import base64
from io import BytesIO
import os
import uuid

import qrcode
import barcode
from barcode.writer import ImageWriter

from app.core.config import settings


def _ensure_dir() -> str:
    os.makedirs(settings.BARCODE_STORAGE_DIR, exist_ok=True)
    return settings.BARCODE_STORAGE_DIR


def generate_barcode_value(prefix: str) -> str:
    """Numeric-only barcode (good for Code128 / EAN-compatibility). Length 13."""
    raw = uuid.uuid4().int
    digits = str(raw)[:12]
    return f"{digits}"


def generate_unique_number(prefix: str, seq: int) -> str:
    return f"{prefix}-{seq:08d}"


def save_qr_image(payload: str, filename_stem: str) -> str:
    """Generate QR PNG for payload, return URL path."""
    _ensure_dir()
    img = qrcode.make(payload)
    full_path = os.path.join(settings.BARCODE_STORAGE_DIR, f"{filename_stem}.png")
    img.save(full_path)
    return f"/storage/barcodes/{filename_stem}.png"


def qr_png_data_uri(payload: str) -> str:
    """Render a QR as an inline PNG without creating a persistent storage file."""
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def save_barcode_image(value: str, filename_stem: str) -> str:
    """Generate Code128 barcode PNG, return URL path."""
    _ensure_dir()
    bclass = barcode.get_barcode_class("code128")
    bc = bclass(value, writer=ImageWriter())
    full_path = os.path.join(settings.BARCODE_STORAGE_DIR, filename_stem)
    saved = bc.save(full_path, options={"write_text": False})
    fname = os.path.basename(saved)
    return f"/storage/barcodes/{fname}"

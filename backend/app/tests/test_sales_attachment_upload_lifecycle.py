import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from anyio import CancelScope
from fastapi import UploadFile
from PIL import Image

from app.api.routes import sales


def _png_bytes() -> bytes:
    data = BytesIO()
    Image.new("RGB", (12, 12), "white").save(data, format="PNG")
    return data.getvalue()


def _stored_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def test_sales_document_upload_persists_valid_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sales.settings, "SALES_ORDER_FILES_DIR", str(tmp_path))
    content = b"%PDF-1.4\nsynthetic attachment"
    upload = UploadFile(file=BytesIO(content), filename="artwork.pdf")

    try:
        response = asyncio.run(sales.upload_printing_attachment(upload, object()))
    finally:
        asyncio.run(upload.close())

    stored_name = response["file_url"].split("/storage/sales-order-files/", 1)[1].split("?", 1)[0]
    assert response["file_name"] == "artwork.pdf"
    assert response["content_type"] == "application/pdf"
    assert (tmp_path / stored_name).read_bytes() == content


def test_sales_document_cancellation_shields_new_file_cleanup(tmp_path, monkeypatch):
    existing = tmp_path / "existing-attachment.pdf"
    existing.write_bytes(b"keep existing attachment")
    monkeypatch.setattr(sales.settings, "SALES_ORDER_FILES_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(b"%PDF-1.4\ncancelled"), filename="cancelled.pdf")

    async def run():
        with CancelScope() as scope:
            def cancel_after_file_write(_path):
                scope.cancel()
                raise asyncio.CancelledError

            monkeypatch.setattr(sales, "sign_path", cancel_after_file_write)
            with pytest.raises(asyncio.CancelledError):
                await sales.upload_printing_attachment(upload, object())
            assert scope.cancel_called

    try:
        asyncio.run(run())
    finally:
        asyncio.run(upload.close())

    assert existing.read_bytes() == b"keep existing attachment"
    assert _stored_files(tmp_path) == {Path(existing.name)}


def test_sales_image_cancellation_shields_new_file_cleanup(tmp_path, monkeypatch):
    existing = tmp_path / "existing-attachment.webp"
    existing.write_bytes(b"keep existing attachment")
    monkeypatch.setattr(sales.settings, "SALES_ORDER_FILES_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(_png_bytes()), filename="cancelled.png")

    async def run():
        with CancelScope() as scope:
            def cancel_after_file_write(_path):
                scope.cancel()
                raise asyncio.CancelledError

            monkeypatch.setattr(sales, "sign_path", cancel_after_file_write)
            with pytest.raises(asyncio.CancelledError):
                await sales.upload_printing_attachment(upload, object())
            assert scope.cancel_called

    try:
        asyncio.run(run())
    finally:
        asyncio.run(upload.close())

    assert existing.read_bytes() == b"keep existing attachment"
    assert _stored_files(tmp_path) == {Path(existing.name)}


def test_sales_document_collision_preserves_preexisting_file(tmp_path, monkeypatch):
    collision = tmp_path / "so_print_collision.pdf"
    collision.write_bytes(b"keep collision attachment")
    monkeypatch.setattr(sales.settings, "SALES_ORDER_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(sales, "uuid4", lambda: SimpleNamespace(hex="collision"))
    upload = UploadFile(file=BytesIO(b"%PDF-1.4\nreplacement"), filename="artwork.pdf")

    try:
        with pytest.raises(FileExistsError):
            asyncio.run(sales.upload_printing_attachment(upload, object()))
    finally:
        asyncio.run(upload.close())

    assert collision.read_bytes() == b"keep collision attachment"
    assert _stored_files(tmp_path) == {Path(collision.name)}

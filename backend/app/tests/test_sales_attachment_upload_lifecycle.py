import asyncio
from io import BytesIO
from pathlib import Path
from threading import Event, Lock, get_ident
import time
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


def test_sales_document_upload_work_leaves_event_loop_and_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(sales.settings, "SALES_ORDER_FILES_DIR", str(tmp_path))
    loop_thread = get_ident()
    active = peak = 0
    lock = Lock()
    original_write = sales._write_new_sales_attachment

    def tracked_write(target, content):
        nonlocal active, peak
        assert get_ident() != loop_thread, "Document storage blocks the event loop"
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.03)
            original_write(target, content)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(sales, "_write_new_sales_attachment", tracked_write)

    async def run():
        uploads = [
            UploadFile(file=BytesIO(b"%PDF-1.4\nsynthetic"), filename=f"artwork-{index}.pdf")
            for index in range(3)
        ]
        try:
            return await asyncio.gather(*[
                sales.upload_printing_attachment(upload, object())
                for upload in uploads
            ])
        finally:
            for upload in uploads:
                await upload.close()

    responses = asyncio.run(run())
    assert peak == 1
    assert len(responses) == 3


def test_sales_document_external_cancellation_waits_then_cleans(tmp_path, monkeypatch):
    monkeypatch.setattr(sales.settings, "SALES_ORDER_FILES_DIR", str(tmp_path))
    worker_started = Event()
    release_worker = Event()
    original_write = sales._write_new_sales_attachment

    def delayed_write(target, content):
        worker_started.set()
        assert release_worker.wait(5), "Document worker was not released"
        original_write(target, content)

    monkeypatch.setattr(sales, "_write_new_sales_attachment", delayed_write)
    upload = UploadFile(file=BytesIO(b"%PDF-1.4\nexternal cancellation"), filename="cancel.pdf")

    async def run():
        task = asyncio.create_task(sales.upload_printing_attachment(upload, object()))
        assert await asyncio.to_thread(worker_started.wait, 5)
        task.cancel()
        release_worker.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(run())
    finally:
        release_worker.set()
        asyncio.run(upload.close())

    assert _stored_files(tmp_path) == set()

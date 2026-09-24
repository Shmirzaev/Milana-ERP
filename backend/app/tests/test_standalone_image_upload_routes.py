import asyncio
from io import BytesIO
from threading import Event

import pytest
from fastapi import UploadFile
from PIL import Image

from app.api.routes import inventory, purchasing
from app.services import image_storage


def _png_bytes() -> bytes:
    data = BytesIO()
    Image.new("RGB", (12, 12), "white").save(data, format="PNG")
    return data.getvalue()


@pytest.mark.parametrize(
    ("route", "prefix"),
    [
        (inventory.upload_item_image, "item_"),
        (purchasing.upload_request_photo, "purchase_"),
    ],
)
def test_standalone_image_upload_route_persists_complete_image_set(
    route,
    prefix,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(inventory.settings, "MODEL_FILES_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(_png_bytes()), filename="source.png")
    try:
        response = asyncio.run(route(upload, object()))
    finally:
        asyncio.run(upload.close())

    stored_name = response["file_url"].rsplit("/", 1)[-1]
    assert stored_name.startswith(prefix)
    assert (tmp_path / stored_name).is_file()
    assert len(list((tmp_path / "_thumbs").glob(f"*{stored_name}.webp"))) == 2


@pytest.mark.parametrize(
    "route",
    [inventory.upload_item_image, purchasing.upload_request_photo],
)
def test_standalone_image_upload_cancellation_removes_partial_files(
    route,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(inventory.settings, "MODEL_FILES_DIR", str(tmp_path))

    def cancel_thumbnail_work(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(image_storage, "prebuild_webp_thumbnails", cancel_thumbnail_work)
    upload = UploadFile(file=BytesIO(_png_bytes()), filename="cancelled.png")
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(route(upload, object()))
    finally:
        asyncio.run(upload.close())

    assert list(tmp_path.rglob("*.webp")) == []


def test_standalone_image_upload_external_cancellation_waits_then_cleans(tmp_path, monkeypatch):
    monkeypatch.setattr(inventory.settings, "MODEL_FILES_DIR", str(tmp_path))
    worker_started = Event()
    release_worker = Event()
    original_convert = image_storage.convert_image_to_webp

    def delayed_convert(content):
        worker_started.set()
        assert release_worker.wait(5), "Image worker was not released"
        return original_convert(content)

    monkeypatch.setattr(image_storage, "convert_image_to_webp", delayed_convert)
    upload = UploadFile(file=BytesIO(_png_bytes()), filename="external-cancel.png")

    async def run():
        task = asyncio.create_task(inventory.upload_item_image(upload, object()))
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

    assert list(tmp_path.rglob("*.webp")) == []

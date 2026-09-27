import asyncio
from io import BytesIO
from pathlib import Path
from threading import Lock, get_ident
import time

from fastapi import UploadFile
from PIL import Image
import pytest

from app.core import uploads
from app.services import image_storage


def _upload():
    stream = BytesIO()
    with Image.new("RGB", (8, 8), "blue") as image:
        image.save(stream, format="PNG")
    stream.seek(0)
    return UploadFile(file=stream, filename="synthetic.png")


def test_image_and_document_uploads_share_configurable_process_capacity(monkeypatch):
    assert image_storage._image_upload_slot is uploads.UPLOAD_PROCESSING_LIMITER
    monkeypatch.setenv("UPLOAD_MAX_CONCURRENCY_PER_PROCESS", "4")
    assert uploads._upload_concurrency_from_environment() == 4
    monkeypatch.setenv("UPLOAD_MAX_CONCURRENCY_PER_PROCESS", "0")
    with pytest.raises(RuntimeError, match="must be between 1 and 32"):
        uploads._upload_concurrency_from_environment()
    monkeypatch.setenv("UPLOAD_MAX_CONCURRENCY_PER_PROCESS", "not-an-integer")
    with pytest.raises(RuntimeError, match="must be an integer"):
        uploads._upload_concurrency_from_environment()


def test_upload_conversion_and_disk_work_leave_event_loop_and_are_bounded(tmp_path, monkeypatch):
    loop_thread = get_ident()
    active = peak = 0
    lock = Lock()
    convert = image_storage.convert_image_to_webp
    write = image_storage._atomic_write
    thumbs = image_storage.prebuild_webp_thumbnails

    def conversion(content):
        nonlocal active, peak
        assert get_ident() != loop_thread, "Image conversion blocks the event loop"
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(.03)
            return convert(content)
        finally:
            with lock:
                active -= 1

    def disk_write(*args, **kwargs):
        assert get_ident() != loop_thread, "Image disk write blocks the event loop"
        return write(*args, **kwargs)

    def thumbnails(*args, **kwargs):
        assert get_ident() != loop_thread, "Thumbnail conversion blocks the event loop"
        return thumbs(*args, **kwargs)

    monkeypatch.setattr(image_storage, "convert_image_to_webp", conversion)
    monkeypatch.setattr(image_storage, "_atomic_write", disk_write)
    monkeypatch.setattr(image_storage, "prebuild_webp_thumbnails", thumbnails)

    async def run():
        uploads = [_upload() for _ in range(3)]
        try:
            return await asyncio.gather(*[
                image_storage.store_uploaded_image(upload, target_dir=str(tmp_path),
                    file_url_base="/storage/test", name_prefix="synthetic", max_bytes=4096,
                    prebuild_thumbnails=True)
                for upload in uploads
            ])
        finally:
            for upload in uploads:
                await upload.close()

    results = asyncio.run(run())
    assert peak == 1, "Parallel uploads must not multiply image-decoding memory"
    assert len({result.file_name for result in results}) == 3
    for result in results:
        assert result.content_type == "image/webp"
        assert (result.width, result.height) == (8, 8)
        assert Path(result.absolute_path).stat().st_size == result.byte_size
        assert len(list((tmp_path / "_thumbs").glob(f"*{result.file_name}.webp"))) == 2


def test_thumbnail_failure_still_propagates_and_removes_original(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic thumbnail failure")

    monkeypatch.setattr(image_storage, "prebuild_webp_thumbnails", fail)

    async def run():
        upload = _upload()
        try:
            await image_storage.store_uploaded_image(upload, target_dir=str(tmp_path),
                file_url_base="/storage/test", name_prefix="synthetic", max_bytes=4096,
                prebuild_thumbnails=True)
        finally:
            await upload.close()

    with pytest.raises(RuntimeError, match="synthetic thumbnail failure"):
        asyncio.run(run())
    assert list(tmp_path.glob("*.webp")) == []

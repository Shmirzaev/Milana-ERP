from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import warnings
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import TypeVar
from uuid import uuid4

from anyio import CapacityLimiter, WouldBlock, to_thread
from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session, sessionmaker

from app.core.uploads import read_validated_image_upload


FULL_IMAGE_QUALITY = 93
THUMBNAIL_QUALITY = 88
WEBP_METHOD = 4
PREBUILT_THUMBNAIL_SIZES = (160, 320)
MAX_IMAGE_PIXELS = 50_000_000

_thumbnail_generation_slot = BoundedSemaphore(1)

# Bounded upload lifecycle. These helpers live here rather than in
# ``app/core/uploads.py`` because the upload routes and this service have to
# share one admission budget; ``app/core/uploads.py`` is outside this change.
_ResultT = TypeVar("_ResultT")

_MAX_UPLOAD_CONCURRENCY = 32
_MAX_QUEUED_UPLOADS = 64


def _upload_concurrency_from_environment() -> int:
    raw = os.environ.get("UPLOAD_MAX_CONCURRENCY_PER_PROCESS", "1")
    try:
        capacity = int(raw)
    except ValueError as exc:
        raise RuntimeError("UPLOAD_MAX_CONCURRENCY_PER_PROCESS must be an integer") from exc
    if capacity < 1 or capacity > _MAX_UPLOAD_CONCURRENCY:
        raise RuntimeError(
            f"UPLOAD_MAX_CONCURRENCY_PER_PROCESS must be between 1 and {_MAX_UPLOAD_CONCURRENCY}"
        )
    return capacity


def _queued_upload_bound_from_environment() -> int:
    raw = os.environ.get("UPLOAD_MAX_QUEUED_PER_PROCESS", "8")
    try:
        bound = int(raw)
    except ValueError as exc:
        raise RuntimeError("UPLOAD_MAX_QUEUED_PER_PROCESS must be an integer") from exc
    if bound < 0 or bound > _MAX_QUEUED_UPLOADS:
        raise RuntimeError(
            f"UPLOAD_MAX_QUEUED_PER_PROCESS must be between 0 and {_MAX_QUEUED_UPLOADS}"
        )
    return bound


# Deliberately process-local. A budget shared by several API processes or by
# several hosts behind the proxy needs deployment-specific infrastructure and
# cannot be inferred safely by the application.
UPLOAD_PROCESSING_LIMITER = CapacityLimiter(_upload_concurrency_from_environment())
UPLOAD_MAX_QUEUED = _queued_upload_bound_from_environment()
_admission_lock = Lock()


@asynccontextmanager
async def upload_processing_slot():
    """Admit upload work up to this process's bound, then reject the excess.

    Waiting never holds a thread, and the queue itself is bounded: an upload
    beyond both the bound and the queue is refused immediately instead of
    parking a fully buffered 20 MiB body in memory indefinitely. The lock only
    covers the admit-or-wait decision, never the upload itself.
    """
    limiter = UPLOAD_PROCESSING_LIMITER
    with _admission_lock:
        try:
            limiter.acquire_nowait()
        except WouldBlock:
            admitted = False
        else:
            admitted = True
    if admitted:
        try:
            yield
        finally:
            limiter.release()
        return
    if limiter.statistics().tasks_waiting >= UPLOAD_MAX_QUEUED:
        raise HTTPException(429, "Too many uploads in progress; retry shortly")
    await limiter.acquire()
    try:
        yield
    finally:
        limiter.release()


async def run_blocking_to_completion(work: Callable[[], _ResultT]) -> _ResultT:
    """Run blocking work in a worker thread and never abandon its outcome.

    A cancelled request (a dropped client connection) cancels the request task
    itself, which would otherwise abandon the thread and leave the caller
    unable to tell whether a transaction committed. Shielding the worker task
    keeps the outcome known, and the pending cancellation is re-raised
    afterwards so the request still ends as cancelled.
    """
    worker = asyncio.ensure_future(to_thread.run_sync(work, abandon_on_cancel=False))
    pending: asyncio.CancelledError | None = None
    while not worker.done():
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError as exc:
            if worker.cancelled():
                raise
            pending = pending or exc
            continue
        if pending is not None:
            raise pending
        return result
    result = worker.result()
    if pending is not None:
        raise pending
    return result


@dataclass
class UploadCommitState:
    committed: bool = False


@dataclass
class UploadFileWriteState:
    created: bool = False


def upload_session_factory(request_db: Session) -> sessionmaker[Session]:
    """Create fresh Sessions on the request's engine for blocking upload SQL."""
    return sessionmaker(
        bind=request_db.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        info=dict(request_db.info),
    )


def _run_upload_db_work(
    factory: sessionmaker[Session],
    work: Callable[[Session], _ResultT],
    *,
    commit: bool,
    commit_state: UploadCommitState,
) -> _ResultT:
    with factory() as worker_db:
        try:
            result = work(worker_db)
            if commit:
                worker_db.commit()
                commit_state.committed = True
            return result
        except BaseException:
            worker_db.rollback()
            raise


async def run_upload_db_work(
    factory: sessionmaker[Session],
    work: Callable[[Session], _ResultT],
    *,
    commit: bool = False,
    commit_state: UploadCommitState | None = None,
) -> _ResultT:
    """Run synchronous SQL in one worker-owned Session/transaction.

    The request session is never touched from the worker thread, so the scope
    and permission decisions the route verified must be re-verified by ``work``
    against this session. Cancellation never abandons the worker: the
    transaction either rolls back or completes before the caller decides whether
    file cleanup is necessary.
    """
    return await run_blocking_to_completion(partial(
        _run_upload_db_work,
        factory,
        work,
        commit=commit,
        commit_state=commit_state or UploadCommitState(),
    ))


async def run_upload_file_write(work: Callable[[], object], state: UploadFileWriteState) -> None:
    def write_and_mark_created() -> None:
        work()
        state.created = True

    await run_blocking_to_completion(write_and_mark_created)


@dataclass(frozen=True)
class ConvertedImage:
    data: bytes
    width: int
    height: int
    has_alpha: bool


@dataclass(frozen=True)
class StoredImage:
    file_name: str
    file_url: str
    absolute_path: str
    content_type: str
    width: int
    height: int
    byte_size: int


def _normalized_image(content: bytes, *, recover_legacy_jpeg: bool = False) -> tuple[Image.Image, bytes | None, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as opened:
                if int(opened.width) * int(opened.height) > MAX_IMAGE_PIXELS:
                    raise HTTPException(400, "Image dimensions are too large")
                source_format = str(opened.format or "").upper()
                icc_profile = opened.info.get("icc_profile")
                frame = ImageOps.exif_transpose(opened)
                frame.load()
                has_alpha = "A" in frame.getbands() or (
                    frame.mode == "P" and "transparency" in opened.info
                )
                normalized = frame.convert("RGBA" if has_alpha else "RGB")
                return normalized, icc_profile, source_format
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, "Image dimensions are too large")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if recover_legacy_jpeg and content.startswith(b"\xff\xd8") and "truncated" in str(exc).lower():
            # Old ERP JPEGs can lack their final bytes. Tolerate that only for
            # existing thumbnail sources, in a separate process: Pillow's flag
            # is global and must never weaken concurrent upload validation.
            try:
                recovered = subprocess.run(
                    [sys.executable, "-c", _LEGACY_JPEG_RECOVERY],
                    input=content,
                    capture_output=True,
                    check=True,
                    timeout=20,
                )
                image, icc_profile, _ = _normalized_image(recovered.stdout)
                return image, icc_profile, "JPEG"
            except (subprocess.SubprocessError, OSError):
                pass
        raise HTTPException(400, "File content is not a supported image")


_LEGACY_JPEG_RECOVERY = """
import sys, warnings
from io import BytesIO
from PIL import Image, ImageFile, ImageOps
warnings.simplefilter('error', Image.DecompressionBombWarning)
ImageFile.LOAD_TRUNCATED_IMAGES = True
with Image.open(BytesIO(sys.stdin.buffer.read())) as source:
    if source.format != 'JPEG' or source.width * source.height > 50_000_000:
        raise ValueError('Not a recoverable JPEG')
    image = ImageOps.exif_transpose(source)
    image.load()
    image.convert('RGB').save(sys.stdout.buffer, format='PNG', icc_profile=source.info.get('icc_profile'))
"""


def _webp_bytes(
    image: Image.Image,
    *,
    source_format: str,
    icc_profile: bytes | None,
    thumbnail: bool,
) -> bytes:
    output = BytesIO()
    has_alpha = "A" in image.getbands()
    lossless_source = source_format in {"PNG", "BMP", "TIFF", "GIF"} or has_alpha
    options: dict[str, object] = {
        "format": "WEBP",
        "method": WEBP_METHOD,
        "exact": has_alpha,
    }
    if thumbnail:
        options.update(quality=THUMBNAIL_QUALITY, lossless=has_alpha)
    elif lossless_source:
        options.update(quality=100, lossless=True)
    else:
        options.update(quality=FULL_IMAGE_QUALITY, lossless=False)
    if icc_profile:
        options["icc_profile"] = icc_profile
    image.save(output, **options)
    data = output.getvalue()
    try:
        with Image.open(BytesIO(data)) as check:
            check.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(500, "Converted image validation failed")
    return data


def convert_image_to_webp(content: bytes) -> ConvertedImage:
    image, icc_profile, source_format = _normalized_image(content)
    try:
        data = _webp_bytes(
            image,
            source_format=source_format,
            icc_profile=icc_profile,
            thumbnail=False,
        )
        return ConvertedImage(
            data=data,
            width=int(image.width),
            height=int(image.height),
            has_alpha="A" in image.getbands(),
        )
    finally:
        image.close()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_prefix(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned[:96] or "image"


def _thumbnail_data(image: Image.Image, size: int, *, source_format: str, icc_profile: bytes | None) -> bytes:
    preview = image.copy()
    try:
        preview.thumbnail((size, size), Image.Resampling.LANCZOS)
        return _webp_bytes(
            preview,
            source_format=source_format,
            icc_profile=icc_profile,
            thumbnail=True,
        )
    finally:
        preview.close()


def prebuild_webp_thumbnails(
    content: bytes,
    *,
    thumbnail_root: str | Path,
    source_file_name: str,
    sizes: tuple[int, ...] = PREBUILT_THUMBNAIL_SIZES,
    recover_legacy_jpeg: bool = False,
) -> list[Path]:
    image, icc_profile, source_format = _normalized_image(content, recover_legacy_jpeg=recover_legacy_jpeg)
    created: list[Path] = []
    previous_content: dict[Path, bytes | None] = {}
    try:
        root = Path(thumbnail_root)
        for raw_size in sizes:
            size = max(96, min(int(raw_size), 1280))
            destination = root / f"{size}_{source_file_name}.webp"
            previous_content[destination] = destination.read_bytes() if destination.exists() else None
            _atomic_write(
                destination,
                _thumbnail_data(
                    image,
                    size,
                    source_format=source_format,
                    icc_profile=icc_profile,
                ),
            )
            created.append(destination)
    except BaseException:
        for path in reversed(created):
            previous = previous_content[path]
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, previous)
        raise
    finally:
        image.close()
    return created


async def store_uploaded_image(
    file: UploadFile,
    *,
    target_dir: str,
    file_url_base: str,
    name_prefix: str,
    max_bytes: int,
    prebuild_thumbnails: bool = False,
) -> StoredImage:
    async with upload_processing_slot():
        content, _ = await read_validated_image_upload(file, max_bytes)
        stored: list[StoredImage] = []

        def store_and_record() -> StoredImage:
            result = _store_image_content(
                content,
                target_dir=target_dir,
                file_url_base=file_url_base,
                name_prefix=name_prefix,
                prebuild_thumbnails=prebuild_thumbnails,
            )
            stored.append(result)
            return result

        try:
            return await run_blocking_to_completion(store_and_record)
        except BaseException:
            # The worker thread always finished, so a stored file is known here
            # and a cancelled request must not leave it behind.
            if stored:
                await discard_stored_image(stored[0])
            raise


def _store_image_content(
    content: bytes,
    *,
    target_dir: str,
    file_url_base: str,
    name_prefix: str,
    prebuild_thumbnails: bool,
) -> StoredImage:
    converted = convert_image_to_webp(content)
    file_name = f"{_safe_prefix(name_prefix)}_{uuid4().hex}.webp"
    absolute_path = Path(target_dir) / file_name
    _atomic_write(absolute_path, converted.data)
    if prebuild_thumbnails:
        try:
            prebuild_webp_thumbnails(
                converted.data,
                thumbnail_root=Path(target_dir) / "_thumbs",
                source_file_name=file_name,
            )
        except BaseException:
            absolute_path.unlink(missing_ok=True)
            raise
    return StoredImage(
        file_name=file_name,
        file_url=f"{file_url_base.rstrip('/')}/{file_name}",
        absolute_path=str(absolute_path),
        content_type="image/webp",
        width=converted.width,
        height=converted.height,
        byte_size=len(converted.data),
    )


async def discard_stored_image(stored: StoredImage) -> None:
    await run_blocking_to_completion(partial(_discard_stored_image_files, stored))


def _discard_stored_image_files(stored: StoredImage) -> None:
    original = Path(stored.absolute_path)
    thumbnail_root = original.parent / "_thumbs"
    for size in PREBUILT_THUMBNAIL_SIZES:
        (thumbnail_root / f"{size}_{stored.file_name}.webp").unlink(missing_ok=True)
    original.unlink(missing_ok=True)


_MANAGED_IMAGE_URL = re.compile(r"^/storage/model-files/([A-Za-z0-9_-]+_[0-9a-f]{32}\.webp)$")


def discard_replaced_managed_image(previous_url: str | None, *, storage_root: str | Path) -> bool:
    """Delete an image that this service stored and that has now been replaced.

    Only managed names produced by ``store_uploaded_image`` are removed, and
    only after the resolved path is proven to sit directly in ``storage_root``.
    The caller owns the "is it still current?" question: it must confirm the
    previous URL is no longer the referenced one before discarding it.
    """
    match = _MANAGED_IMAGE_URL.fullmatch(str(previous_url or "").strip())
    if match is None:
        return False
    root = Path(storage_root).resolve()
    image_path = (root / match.group(1)).resolve()
    if image_path.parent != root:
        return False
    thumbnail_root = root / "_thumbs"
    resolved_thumbnail_root = thumbnail_root.resolve()
    if resolved_thumbnail_root.parent != root:
        return False
    for size in PREBUILT_THUMBNAIL_SIZES:
        thumbnail = thumbnail_root / f"{size}_{match.group(1)}.webp"
        if thumbnail.resolve().parent == resolved_thumbnail_root:
            thumbnail.unlink(missing_ok=True)
    if not image_path.is_file():
        return False
    image_path.unlink()
    return True


def ensure_webp_thumbnail(
    *,
    destination_path: str,
    size: int,
    source_path: str | None = None,
    image_data: bytes | None = None,
) -> None:
    destination = Path(destination_path)
    if destination.is_file():
        return
    with _thumbnail_generation_slot:
        if destination.is_file():
            return
        if source_path:
            content = Path(source_path).read_bytes()
        else:
            content = bytes(image_data or b"")
        if not content:
            raise HTTPException(404, "Image source not found")
        created = prebuild_webp_thumbnails(
            content,
            thumbnail_root=destination.parent,
            source_file_name=_source_name_from_thumbnail(destination.name, size),
            sizes=(size,),
            recover_legacy_jpeg=True,
        )
        generated = created[0]
        if generated != destination:
            os.replace(generated, destination)


def _source_name_from_thumbnail(thumbnail_name: str, size: int) -> str:
    prefix = f"{size}_"
    suffix = ".webp"
    if thumbnail_name.startswith(prefix) and thumbnail_name.endswith(suffix):
        return thumbnail_name[len(prefix) : -len(suffix)]
    return thumbnail_name

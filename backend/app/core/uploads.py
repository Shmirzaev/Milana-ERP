from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TypeVar

from anyio import CapacityLimiter, to_thread
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session, sessionmaker


SAFE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
SAFE_DOCUMENT_EXTENSIONS = {".pdf", ".dxf", ".ai"}

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".pdf": "application/pdf",
    ".dxf": "application/dxf",
    ".ai": "application/postscript",
}

_MAX_UPLOAD_CONCURRENCY = 32
_ResultT = TypeVar("_ResultT")


@dataclass
class UploadCommitState:
    committed: bool = False


@dataclass
class UploadFileWriteState:
    created: bool = False


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


# This is deliberately process-local. A shared/global admission budget requires
# deployment-specific infrastructure (for example Redis) and cannot be inferred
# safely by the application.
UPLOAD_PROCESSING_LIMITER = CapacityLimiter(_upload_concurrency_from_environment())


@asynccontextmanager
async def upload_processing_slot():
    """Bound full-file buffering and storage work within this API process."""
    async with UPLOAD_PROCESSING_LIMITER:
        yield


def upload_session_factory(request_db: Session) -> sessionmaker[Session]:
    """Create fresh Sessions on the request's engine for blocking upload work."""
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
    failure_cleanup: Callable[[], None] | None,
) -> _ResultT:
    with factory() as worker_db:
        try:
            result = work(worker_db)
            if commit:
                worker_db.commit()
                commit_state.committed = True
            return result
        except BaseException:
            try:
                if failure_cleanup is not None:
                    failure_cleanup()
            finally:
                worker_db.rollback()
            raise


async def run_upload_db_work(
    factory: sessionmaker[Session],
    work: Callable[[Session], _ResultT],
    *,
    commit: bool = False,
    commit_state: UploadCommitState | None = None,
    failure_cleanup: Callable[[], None] | None = None,
) -> _ResultT:
    """Run synchronous SQL in one worker-owned Session/transaction.

    Cancellation never abandons the worker: the transaction either rolls back
    or completes before the caller decides whether file cleanup is necessary.
    """
    state = commit_state or UploadCommitState()
    return await run_sync_to_completion(partial(
        _run_upload_db_work,
        factory,
        work,
        commit=commit,
        commit_state=state,
        failure_cleanup=failure_cleanup,
    ))


async def run_sync_to_completion(work: Callable[[], _ResultT]) -> _ResultT:
    """Run blocking work without abandoning it on raw asyncio cancellation."""
    worker = asyncio.create_task(
        to_thread.run_sync(work, abandon_on_cancel=False)
    )
    pending_cancellation: asyncio.CancelledError | None = None
    while not worker.done():
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError as exc:
            # Raw task cancellation bypasses AnyIO cancellation scopes. Keep
            # waiting until the transaction outcome and ownership marker are
            # known before the route decides whether to remove its file.
            pending_cancellation = exc
            continue
        else:
            if pending_cancellation is not None:
                raise pending_cancellation
            return result
    result = worker.result()
    if pending_cancellation is not None:
        raise pending_cancellation
    return result


async def run_upload_file_write(
    work: Callable[[], object],
    state: UploadFileWriteState,
) -> None:
    def write_and_mark_created() -> None:
        work()
        state.created = True

    await run_sync_to_completion(write_and_mark_created)


def extension_for_upload(file: UploadFile, allowed_extensions: set[str]) -> str:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise HTTPException(400, f"Unsupported file type. Allowed: {allowed}")
    return ext


def validated_upload_content(content: bytes, ext: str, max_bytes: int) -> bytes:
    if not content:
        raise HTTPException(400, "Empty file")
    if len(content) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise HTTPException(400, f"File too large (max {mb}MB)")
    if not _matches_extension(content, ext):
        raise HTTPException(400, "File content does not match the file extension")
    return content


def detected_image_extension(content: bytes) -> str | None:
    head = content[:512]
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head.startswith(b"BM"):
        return ".bmp"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    return None


async def read_validated_image_upload(
    file: UploadFile,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> tuple[bytes, str]:
    extension_for_upload(file, SAFE_IMAGE_EXTENSIONS)
    content = await read_bounded_upload_content(file, max_bytes, chunk_size)
    actual_ext = detected_image_extension(content)
    if not actual_ext:
        raise HTTPException(400, "File content is not a supported image")
    return content, actual_ext


async def read_validated_upload_content(file, ext: str, max_bytes: int, chunk_size: int = 1024 * 1024) -> bytes:
    """Read and validate an UploadFile without ever issuing an unbounded read()."""
    content = await read_bounded_upload_content(file, max_bytes, chunk_size)
    return validated_upload_content(content, ext, max_bytes)


async def read_bounded_upload_content(
    file: UploadFile,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            mb = max_bytes // (1024 * 1024)
            raise HTTPException(400, f"File too large (max {mb}MB)")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(400, "Empty file")
    return content


def safe_content_type(ext: str) -> str:
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def _matches_extension(content: bytes, ext: str) -> bool:
    if ext in {".jpg", ".jpeg"}:
        return detected_image_extension(content) == ".jpg"
    if ext in SAFE_IMAGE_EXTENSIONS:
        return detected_image_extension(content) == ext
    head = content[:512]
    if ext == ".pdf":
        return head.lstrip().startswith(b"%PDF-")
    if ext == ".ai":
        stripped = head.lstrip()
        return stripped.startswith((b"%PDF-", b"%!PS-Adobe"))
    if ext == ".dxf":
        sample = head.decode("utf-8", errors="ignore").upper()
        return "SECTION" in sample or "ACAD" in sample
    return False

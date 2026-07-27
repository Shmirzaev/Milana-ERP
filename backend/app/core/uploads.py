from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile


SAFE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SAFE_DOCUMENT_EXTENSIONS = {".pdf", ".dxf", ".ai"}

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".dxf": "application/dxf",
    ".ai": "application/postscript",
}


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
    return None


async def read_validated_image_upload(
    file: UploadFile,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> tuple[bytes, str]:
    extension_for_upload(file, SAFE_IMAGE_EXTENSIONS)
    content = await _read_bounded_upload_content(file, max_bytes, chunk_size)
    actual_ext = detected_image_extension(content)
    if not actual_ext:
        raise HTTPException(400, "File content is not a supported image")
    return content, actual_ext


async def read_validated_upload_content(file, ext: str, max_bytes: int, chunk_size: int = 1024 * 1024) -> bytes:
    """Read and validate an UploadFile without ever issuing an unbounded read()."""
    content = await _read_bounded_upload_content(file, max_bytes, chunk_size)
    return validated_upload_content(content, ext, max_bytes)


async def _read_bounded_upload_content(file, max_bytes: int, chunk_size: int) -> bytes:
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

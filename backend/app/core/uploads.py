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


def safe_content_type(ext: str) -> str:
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def _matches_extension(content: bytes, ext: str) -> bool:
    head = content[:512]
    if ext in {".jpg", ".jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == ".pdf":
        return head.lstrip().startswith(b"%PDF-")
    if ext == ".ai":
        stripped = head.lstrip()
        return stripped.startswith((b"%PDF-", b"%!PS-Adobe"))
    if ext == ".dxf":
        sample = head.decode("utf-8", errors="ignore").upper()
        return "SECTION" in sample or "ACAD" in sample
    return False

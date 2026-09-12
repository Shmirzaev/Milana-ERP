from __future__ import annotations

import os
import re
import subprocess
import sys
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.uploads import read_validated_image_upload


FULL_IMAGE_QUALITY = 93
THUMBNAIL_QUALITY = 88
WEBP_METHOD = 4
PREBUILT_THUMBNAIL_SIZES = (160, 320)
MAX_IMAGE_PIXELS = 50_000_000

_thumbnail_generation_slot = BoundedSemaphore(1)


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
    try:
        root = Path(thumbnail_root)
        for raw_size in sizes:
            size = max(96, min(int(raw_size), 1280))
            destination = root / f"{size}_{source_file_name}.webp"
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
    content, _ = await read_validated_image_upload(file, max_bytes)
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
        except Exception:
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

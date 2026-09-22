from __future__ import annotations

import asyncio
from io import BytesIO
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops, ImageStat

from app.services import image_storage
from app.services.image_storage import convert_image_to_webp, prebuild_webp_thumbnails


def _image_bytes(fmt: str, mode: str = "RGB") -> bytes:
    image = Image.new(mode, (640, 480), (42, 118, 176, 127) if mode == "RGBA" else (42, 118, 176))
    output = BytesIO()
    image.save(output, format=fmt, quality=96)
    image.close()
    return output.getvalue()


def test_jpeg_conversion_is_webp_and_visually_lossless():
    source_data = _image_bytes("JPEG")
    converted = convert_image_to_webp(source_data)

    assert converted.data.startswith(b"RIFF")
    assert converted.data[8:12] == b"WEBP"
    assert (converted.width, converted.height) == (640, 480)

    with Image.open(BytesIO(source_data)) as source, Image.open(BytesIO(converted.data)) as result:
        difference = ImageChops.difference(source.convert("RGB"), result.convert("RGB"))
        mean_error = sum(ImageStat.Stat(difference).mean) / 3
        assert mean_error < 2.0


def test_alpha_image_conversion_preserves_pixels_losslessly():
    source_data = _image_bytes("PNG", "RGBA")
    converted = convert_image_to_webp(source_data)

    assert converted.has_alpha is True
    with Image.open(BytesIO(source_data)) as source, Image.open(BytesIO(converted.data)) as result:
        assert source.convert("RGBA").tobytes() == result.convert("RGBA").tobytes()


def test_prebuilt_thumbnails_are_webp_with_expected_bounds(tmp_path):
    created = prebuild_webp_thumbnails(
        _image_bytes("JPEG"),
        thumbnail_root=tmp_path,
        source_file_name="sample.webp",
    )

    assert {path.name for path in created} == {"160_sample.webp.webp", "320_sample.webp.webp"}
    for path, expected_size in zip(created, (160, 320), strict=True):
        with Image.open(path) as image:
            assert image.format == "WEBP"
            assert max(image.size) == expected_size


def test_prebuilt_thumbnails_roll_back_when_a_later_size_fails(tmp_path, monkeypatch):
    source_data = _image_bytes("JPEG")
    original = image_storage._thumbnail_data
    pre_existing = tmp_path / "160_sample.webp.webp"
    pre_existing.write_bytes(b"keep the previous thumbnail")
    unrelated = tmp_path / "160_other.webp"
    unrelated.write_bytes(b"keep this unrelated thumbnail")

    def fail_on_second_size(image, size, *, source_format, icc_profile):
        if size == 320:
            raise RuntimeError("thumbnail conversion failed")
        return original(image, size, source_format=source_format, icc_profile=icc_profile)

    monkeypatch.setattr(image_storage, "_thumbnail_data", fail_on_second_size)

    with pytest.raises(RuntimeError, match="thumbnail conversion failed"):
        prebuild_webp_thumbnails(
            source_data,
            thumbnail_root=tmp_path,
            source_file_name="sample.webp",
        )

    assert pre_existing.read_bytes() == b"keep the previous thumbnail"
    assert unrelated.read_bytes() == b"keep this unrelated thumbnail"
    assert not (tmp_path / "320_sample.webp.webp").exists()


def test_upload_name_collision_preserves_existing_original_and_thumbnails(tmp_path, monkeypatch):
    collision_name = "synthetic_collision.webp"
    previous_original = tmp_path / collision_name
    previous_original.write_bytes(b"keep previous original")
    previous_thumbnails = [
        tmp_path / "_thumbs" / f"{size}_{collision_name}.webp"
        for size in image_storage.PREBUILT_THUMBNAIL_SIZES
    ]
    for path in previous_thumbnails:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"keep previous {path.name}".encode())

    sequence = count()

    def predictable_uuid():
        number = next(sequence)
        return SimpleNamespace(hex="collision" if number == 0 else f"fresh{number}")

    monkeypatch.setattr(image_storage, "uuid4", predictable_uuid)
    stored = image_storage._store_image_content(
        _image_bytes("PNG"),
        target_dir=str(tmp_path),
        file_url_base="/storage/test",
        name_prefix="synthetic",
        prebuild_thumbnails=True,
    )

    assert stored.file_name != collision_name
    assert previous_original.read_bytes() == b"keep previous original"
    assert all(path.read_bytes() == f"keep previous {path.name}".encode() for path in previous_thumbnails)

    asyncio.run(image_storage.discard_stored_image(stored))
    assert not Path(stored.absolute_path).exists()
    assert previous_original.read_bytes() == b"keep previous original"
    assert all(path.read_bytes() == f"keep previous {path.name}".encode() for path in previous_thumbnails)

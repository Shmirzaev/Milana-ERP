from __future__ import annotations

from pathlib import Path

from PIL import Image

from scripts import trim_old_erp_catalog_gray_padding as correction


def save_lossless(path: Path, image: Image.Image) -> None:
    image.save(path, format="WEBP", lossless=True, quality=100, method=1)


def padded_image(path: Path, *, gray_rows: int) -> tuple[Image.Image, str]:
    image = Image.new("RGB", (40, 60), (30, 40, 50))
    for x in range(5, 35):
        for y in range(4, 60 - gray_rows):
            image.putpixel((x, y), (150, 20 + y, 90))
    for y in range(60 - gray_rows, 60):
        for x in range(40):
            image.putpixel((x, y), correction.GRAY)
    expected = correction.pixel_sha256(image.crop((0, 0, 40, 60 - gray_rows)))
    save_lossless(path, image)
    return image, expected


def test_inspect_source_finds_only_material_exact_gray_tail(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.webp"
    original, expected = padded_image(candidate, gray_rows=24)
    try:
        spec = correction.inspect_source(candidate)
        assert spec is not None
        assert spec["width"] == 40
        assert spec["height"] == 60
        assert spec["bottom_gray_rows"] == 24
        assert spec["content_height"] == 36
        assert spec["cropped_pixel_sha256"] == expected
        assert spec["target_name"].startswith(correction.TARGET_PREFIX)
    finally:
        original.close()

    insignificant = tmp_path / "insignificant.webp"
    image, _ = padded_image(insignificant, gray_rows=correction.MIN_GRAY_ROWS - 1)
    image.close()
    assert correction.inspect_source(insignificant) is None


def test_gray_pixels_inside_photo_are_not_removed(tmp_path: Path) -> None:
    candidate = tmp_path / "interior-gray.webp"
    image = Image.new("RGB", (32, 48), (10, 20, 30))
    for x in range(32):
        image.putpixel((x, 20), correction.GRAY)
    for y in range(30, 48):
        for x in range(32):
            image.putpixel((x, y), correction.GRAY)
    image.putpixel((7, 29), (200, 100, 10))
    save_lossless(candidate, image)
    image.close()

    spec = correction.inspect_source(candidate)
    assert spec is not None
    assert spec["bottom_gray_rows"] == 18
    assert spec["content_height"] == 30


def test_lossless_trim_preserves_source_and_content_pixels(tmp_path: Path) -> None:
    source = tmp_path / "source.webp"
    image, expected = padded_image(source, gray_rows=20)
    image.close()
    source_hash = correction.file_sha256(source)
    spec = correction.inspect_source(source)
    assert spec is not None
    spec["target_name"] = "trimmed.webp"

    created, thumbnails = correction.create_trimmed_files([spec], tmp_path)

    assert created == [tmp_path / "trimmed.webp"]
    assert len(thumbnails) == len(correction.THUMBNAIL_SIZES)
    assert correction.file_sha256(source) == source_hash
    correction.validate_source(source, spec)
    correction.validate_target(tmp_path / "trimmed.webp", spec)
    with Image.open(tmp_path / "trimmed.webp") as trimmed:
        pixels = trimmed.convert("RGB")
        assert pixels.size == (40, 40)
        assert correction.pixel_sha256(pixels) == expected
        pixels.close()


def test_canonical_identity_is_order_independent_for_mapping_keys() -> None:
    first = {"name": "a", "rows": 20}
    second = {"rows": 20, "name": "a"}
    assert correction.canonical_sha256(first) == correction.canonical_sha256(second)

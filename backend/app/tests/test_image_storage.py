from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageChops, ImageStat

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

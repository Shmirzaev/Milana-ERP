"""QR image compatibility using the required test-only ZXing decoder."""
import base64
from io import BytesIO

import pytest
from PIL import Image

import zxingcpp as zxing
from app.models import barcode_service


@pytest.mark.parametrize("payload", [
    "BUNDLE:BND-10000|123456789012|PO:PO-10000",
    "PACKAGE:Paxta-ўзбек-😀|123456789012",
    "https://example.invalid/sewing/" + "batch-reference-1234567890/" * 18,
])
def test_png_round_trip_across_real_service_paths(payload, tmp_path, monkeypatch):
    monkeypatch.setattr(barcode_service.settings, "BARCODE_STORAGE_DIR", str(tmp_path))
    png = barcode_service.qr_png_bytes(payload)
    uri = barcode_service.qr_png_data_uri(payload)
    assert uri.startswith("data:image/png;base64,")
    inline = base64.b64decode(uri.split(",", 1)[1], validate=True)
    assert inline == png
    assert barcode_service.save_qr_image(payload, "fixture") == "/storage/barcodes/fixture.png"
    for encoded in (png, inline, (tmp_path / "fixture.png").read_bytes()):
        with Image.open(BytesIO(encoded)) as image:
            assert image.format == "PNG"
            image.load()
            decoded = zxing.read_barcode(image)
            assert decoded is not None
            assert decoded.text == payload


def test_current_image_does_not_reuse_stale_file(tmp_path, monkeypatch):
    monkeypatch.setattr(barcode_service.settings, "BARCODE_STORAGE_DIR", str(tmp_path))
    old = "BUNDLE:BND-10000|123456789012|PO:PO-OLD"
    current = "BUNDLE:BND-10000|123456789012|PO:PO-10000"
    barcode_service.save_qr_image(old, "stale")
    stale = (tmp_path / "stale.png").read_bytes()
    fresh = barcode_service.qr_png_bytes(current)
    for encoded, expected in ((stale, old), (fresh, current)):
        with Image.open(BytesIO(encoded)) as image:
            assert zxing.read_barcode(image).text == expected
    assert (tmp_path / "stale.png").read_bytes() == stale

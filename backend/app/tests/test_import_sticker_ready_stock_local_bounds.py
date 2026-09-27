from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_sticker_ready_stock_local.py"
SPEC = importlib.util.spec_from_file_location("import_sticker_ready_stock_local", SCRIPT)
assert SPEC and SPEC.loader
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)


def _nested_json(levels: int) -> dict:
    nested = {}
    for _ in range(levels):
        nested = {"nested": nested}
    return nested


@pytest.mark.parametrize("source_extra", [
    {"legacy_extension": "x" * importer.MAX_SOURCE_PAYLOAD_BYTES},
    {"legacy_extension": _nested_json(importer.MAX_SOURCE_PAYLOAD_DEPTH)},
    {"legacy_extension": float("nan")},
])
def test_sticker_import_rejects_unbounded_payload_before_database_session(tmp_path, monkeypatch, source_extra):
    photo_root = tmp_path / "photos"
    photo_root.mkdir()
    photo = photo_root / "evidence.jpg"
    photo.write_bytes(b"reviewed sticker evidence")
    photo_hash = hashlib.sha256(photo.read_bytes()).hexdigest()
    row = {
        "qr_code": "uzerp_ii_12345_1",
        "client": "Customer",
        "model_number": "XJ3142",
        "article": "V-43",
        "color": "Blue",
        "product": "Dress",
        "quantity": 10,
        "weight_kg": 2.5,
        "sizes": ["M"],
        "source_photo": photo.name,
        "source_photo_sha256": photo_hash,
        "review_status": "approved",
        **source_extra,
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": 1, "rows": [row]}), encoding="utf-8")
    args = SimpleNamespace(
        apply_local=False,
        input=manifest,
        photo_root=photo_root,
        warehouse_id=8,
        imported_by=None,
    )
    monkeypatch.setattr(
        importer,
        "SessionLocal",
        lambda: pytest.fail("source payload validation must precede database access"),
    )

    expected = "finite JSON" if isinstance(source_extra["legacy_extension"], float) else "source_payload"
    with pytest.raises(ValueError, match=expected):
        importer.run_import(args)

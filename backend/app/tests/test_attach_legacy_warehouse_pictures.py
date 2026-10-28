import hashlib
import json
from pathlib import Path

import pytest

from scripts.attach_legacy_warehouse_pictures import read_manifest, verify_source


def _row(path: Path) -> dict:
    return {
        "model_id": 1,
        "file_name": path.name,
        "file_url": f"/storage/model-files/{path.name}",
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_size_bytes": path.stat().st_size,
        "source_width": 1,
        "source_height": 1,
        "warehouse_package_ids": list(range(1, 468)),
        "expected_warehouse_package_images": [],
    }


def test_manifest_rejects_hash_change(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 changed"):
        read_manifest(manifest, "0" * 64)


def test_manifest_rejects_unsafe_picture_filename(tmp_path):
    picture = tmp_path / "one.png"
    picture.write_bytes(b"not-used")
    row = _row(picture)
    row["file_name"] = "../one.png"
    rows = []
    next_package_id = 1
    for index in range(1, 258):
        package_count = 2 if index <= 210 else 1
        package_ids = list(range(next_package_id, next_package_id + package_count))
        next_package_id += package_count
        rows.append(dict(row, model_id=index, warehouse_package_ids=package_ids))
    payload = {
        "version": 1,
        "image_type": "warehouse_package",
        "expected_alembic_head": "0113_variant_selling_price",
        "summary": {"models": 257, "package_rows": 467, "unique_files": 1},
        "rows": rows,
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe picture filename"):
        read_manifest(manifest, hashlib.sha256(manifest.read_bytes()).hexdigest())


def test_verify_source_rejects_changed_original(tmp_path):
    picture = tmp_path / "one.png"
    picture.write_bytes(b"changed")
    row = _row(picture)
    row["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Source picture changed"):
        verify_source(picture, row)

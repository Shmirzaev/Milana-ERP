from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "ops" / "import_completed_packs.py"
SPEC = importlib.util.spec_from_file_location("import_completed_packs", SCRIPT)
assert SPEC and SPEC.loader
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)


def _row(photo_hash: str) -> dict:
    return {
        "qr_code": "uzerp_ii_19809_1",
        "model_number": "XJ3142",
        "article": "V-43",
        "sizes": ["3XL-54"],
        "weight_kg": "22.8",
        "quantity": 60,
        "source_photo": "evidence.jpg",
        "source_photo_sha256": photo_hash,
        "source_reference": "Completed workbook row 1026",
        "source_workbook_sha256": "a" * 64,
        "review_status": "approved",
        "allowed_blank_weight": False,
        "target_kind": "hidden_legacy",
        "original_model_number": "XJ3142",
        "original_article": "V-43",
    }


def test_hidden_model_code_is_stable_and_identity_scoped():
    row = _row("b" * 64)
    assert importer.hidden_model_code(row) == "LEGACY-STICKER-F35066A57AA572AA"
    changed = {**row, "original_article": "V-44"}
    assert importer.hidden_model_code(changed) != importer.hidden_model_code(row)


def test_validate_hidden_model_rejects_visible_catalog_row():
    row = _row("b" * 64)
    model = SimpleNamespace(
        code=importer.hidden_model_code(row),
        status="approved",
        details_json={
            "legacy_import": True,
            "general": {"model_no": "XJ3142", "variant_no": "V-43"},
        },
    )
    importer.validate_hidden_model(model, row)
    model.details_json["legacy_import"] = False
    with pytest.raises(ValueError, match="hidden model guard failed"):
        importer.validate_hidden_model(model, row)


def test_version_two_manifest_preserves_hidden_identity(tmp_path: Path):
    photo = tmp_path / "evidence.jpg"
    photo.write_bytes(b"photo evidence")
    photo_hash = hashlib.sha256(photo.read_bytes()).hexdigest()
    row = _row(photo_hash)
    payload = {
        "version": 2,
        "expected_rows": 1,
        "expected_quantity": 60,
        "expected_known_weight_kg": "22.8",
        "expected_null_weight_rows": 0,
        "expected_unique_identities": 1,
        "rows": [row],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()

    loaded, rows = importer.read_manifest(manifest, tmp_path, manifest_hash)

    assert loaded["version"] == 2
    assert rows[0]["target_kind"] == "hidden_legacy"
    assert rows[0]["original_model_number"] == "XJ3142"
    assert rows[0]["original_article"] == "V-43"

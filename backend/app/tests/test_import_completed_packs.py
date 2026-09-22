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


def test_production_migration_guard_matches_current_baseline():
    assert importer.EXPECTED_ALEMBIC_HEAD == "0132_first_grade_singles"


def test_reviewed_catalog_selection_requires_original_variant_identity():
    def model(model_id, original):
        return SimpleNamespace(id=model_id, status="approved", details_json={
            "general": {"model_no": "PJ1118", "variant_no": "V-2922"},
            "old_erp_migration": {"identity": original},
        })
    correct = model(3669, "PJ1118|2922")
    duplicate = model(7062, "PJ1118|3881")
    db = SimpleNamespace(query=lambda _: SimpleNamespace(all=lambda: [correct, duplicate]))
    row = dict(qr_code="uzerp_ii_21278_1", target_kind="catalog", model_number="PJ1118",
               article="V-2922", reviewed_catalog_model_id=3669)
    resolved, created = importer.resolve_all(db, [row], 1)
    assert resolved[row["qr_code"]] is correct and created == 0
    row["reviewed_catalog_model_id"] = 7062
    with pytest.raises(ValueError, match="expected one approved catalog model"):
        importer.resolve_all(db, [row], 1)
    del row["reviewed_catalog_model_id"]
    with pytest.raises(ValueError, match="expected one approved catalog model"):
        importer.resolve_all(db, [row], 1)


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
    assert "record_key" not in rows[0]


def test_version_three_allows_no_qr_and_unknown_hidden_identity(tmp_path: Path):
    photo = tmp_path / "unknown.jpg"
    photo.write_bytes(b"unknown sticker evidence")
    photo_hash = hashlib.sha256(photo.read_bytes()).hexdigest()
    row = {
        "record_key": "completed-workbook-record-2000-0123456789abcdef",
        "qr_code": None,
        "has_source_qr": False,
        "package_barcode": "noqr-2000-0123456789abcdef",
        "package_no": "OLD-NOQR-2000-0123456789ABCDEF",
        "model_number": "",
        "article": "",
        "sizes": [],
        "weight_kg": None,
        "quantity": 60,
        "quantity_defaulted": True,
        "source_photo": photo.name,
        "source_photo_sha256": photo_hash,
        "source_reference": "Completed workbook row 2005",
        "source_workbook_sha256": "a" * 64,
        "review_status": "approved",
        "allowed_blank_weight": True,
        "allowed_blank_sizes": True,
        "target_kind": "hidden_legacy",
        "original_model_number": "",
        "original_article": "",
    }
    payload = {
        "version": 3,
        "expected_rows": 1,
        "expected_quantity": 60,
        "expected_known_weight_kg": "0",
        "expected_null_weight_rows": 1,
        "expected_unique_identities": 1,
        "expected_source_qr_rows": 0,
        "expected_no_source_qr_rows": 1,
        "expected_default_quantity_rows": 1,
        "expected_catalog_rows": 0,
        "expected_hidden_legacy_rows": 1,
        "rows": [row],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()

    _, rows = importer.read_manifest(manifest, tmp_path, manifest_hash)

    assert rows[0]["qr_code"] is None
    assert rows[0]["record_key"] == row["record_key"]
    assert rows[0]["quantity"] == 60
    assert rows[0]["sizes"] == []
    assert importer.row_package_barcode(rows[0]) == row["package_barcode"]
    assert importer.hidden_model_code(rows[0]).startswith("LEGACY-STICKER-")

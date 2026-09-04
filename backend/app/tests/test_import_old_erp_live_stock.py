from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_script("build_old_erp_live_stock_manifest", ROOT / "ops" / "build_old_erp_live_stock_manifest.py")
importer = load_script("import_old_erp_live_stock", ROOT / "ops" / "import_old_erp_live_stock.py")


def test_normalize_size_rows_requires_exact_integer_distribution():
    assert builder.normalize_size_rows([("M-46", 40), ("L-48", 40)], 40) == [
        ("M-46", 20),
        ("L-48", 20),
    ]
    with pytest.raises(ValueError, match="fractional"):
        builder.normalize_size_rows([("M-46", 2), ("L-48", 1)], 10)


def test_compact_totals_are_authoritative_and_reject_duplicates(tmp_path: Path):
    totals = tmp_path / "totals.txt"
    totals.write_text("# report-pages=1-81\n1104:20:2\n1105:0:0\n", encoding="utf-8")
    assert builder.load_compact_totals(totals) == {"1104": (20, 2), "1105": (0, 0)}

    totals.write_text("1104:20:2\n1104:20:2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate live-total QR"):
        builder.load_compact_totals(totals)


def test_hidden_model_code_matches_existing_legacy_identity_scheme():
    assert importer.hidden_model_code(("XJ3075", "2362")) == "LEGACY-STICKER-12254BCC6E910B4F"


def test_validate_row_preserves_qr_sizes_and_blank_weight_approval():
    row = {
        "source_record_id": "1104",
        "external_qr": "1104",
        "qr_code": "uzerp_ii_1104_1",
        "package_no": "OLD-1104-1",
        "quantity": 20,
        "candidate_quantity": 20,
        "exhaustive_quantity": 20,
        "quantity_source": "exhaustive_item_barcode_report",
        "quantity_corrected_from_live_query": False,
        "weight_kg": None,
        "allowed_blank_weight": True,
        "color": "Not specified",
        "items": [
            {
                "model_number": "BJ5001",
                "variant_number": "V-738",
                "size": "M-46",
                "quantity": 20,
                "target_kind": "catalog",
                "expected_model_id": 1534,
                "expected_model_code": "ВJ5001-738",
            }
        ],
    }
    validated = importer.validate_row(row)
    assert validated["qr_code"] == "uzerp_ii_1104_1"
    assert validated["items"][0]["size"] == "M-46"

    row["quantity"] = 19
    row["exhaustive_quantity"] = 19
    row["quantity_corrected_from_live_query"] = True
    with pytest.raises(ValueError, match="item rows"):
        importer.validate_row(row)


def test_validate_row_allows_reviewed_direct_quantity_override():
    row = {
        "source_record_id": "3313",
        "external_qr": "3313",
        "qr_code": "uzerp_ii_3313_1",
        "package_no": "OLD-3313-1",
        "quantity": 126,
        "candidate_quantity": 126,
        "exhaustive_quantity": 270,
        "quantity_source": "direct_exact_query",
        "quantity_corrected_from_live_query": False,
        "weight_kg": None,
        "allowed_blank_weight": True,
        "color": "Not specified",
        "items": [
            {
                "model_number": "BJ5001",
                "variant_number": "V-738",
                "size": "M-46",
                "quantity": 126,
                "target_kind": "catalog",
                "expected_model_id": 1534,
                "expected_model_code": "ВJ5001-738",
            }
        ],
    }
    assert importer.validate_row(row)["quantity"] == 126

    row["quantity_source"] = "exhaustive_item_barcode_report"
    with pytest.raises(ValueError, match="does not match"):
        importer.validate_row(row)


def test_read_manifest_checks_all_evidence_hashes(tmp_path: Path):
    evidence = {}
    for name in ("plan.json", "summary.json", "sizes.txt", "prior.jsonl", "resolution.json"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        evidence[name] = {"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    row = {
        "source_record_id": "1104",
        "external_qr": "1104",
        "qr_code": "uzerp_ii_1104_1",
        "package_no": "OLD-1104-1",
        "quantity": 20,
        "candidate_quantity": 20,
        "exhaustive_quantity": 20,
        "quantity_source": "exhaustive_item_barcode_report",
        "quantity_corrected_from_live_query": False,
        "weight_kg": None,
        "allowed_blank_weight": True,
        "color": "Not specified",
        "items": [
            {
                "model_number": "BJ5001",
                "variant_number": "V-738",
                "size": "M-46",
                "quantity": 20,
                "target_kind": "catalog",
                "expected_model_id": 1534,
                "expected_model_code": "ВJ5001-738",
            }
        ],
    }
    payload = {
        "version": 1,
        "source_system": "UZERP_LIVE_STOCK",
        "source_warehouse_id": "18",
        "source_warehouse_name": "TAYYOR MAHSULOT OMBORI",
        "destination_warehouse_id": 8,
        "destination_warehouse_name": "Finished Goods",
        "source_files": evidence,
        "expected_packages": 1,
        "expected_quantity": 20,
        "expected_item_rows": 1,
        "expected_corrected_quantity_packages": 0,
        "expected_hidden_legacy_items": 0,
        "held_packages": [],
        "rows": [row],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()

    _, rows = importer.read_manifest(manifest, manifest_hash, tmp_path)
    assert len(rows) == 1

    (tmp_path / "sizes.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="missing or changed"):
        importer.read_manifest(manifest, manifest_hash, tmp_path)

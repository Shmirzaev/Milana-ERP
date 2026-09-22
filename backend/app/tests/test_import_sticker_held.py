"""Safety checks for the explicitly scoped old-ERP continuation import."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

OPS = Path(__file__).resolve().parents[3] / "ops"
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location("held_import", OPS / "import_sticker_held_20260922.py")
held = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(held)


def source_fixture(tmp_path, mutate=None):
    (tmp_path / "source.json").write_text("source evidence")
    (tmp_path / "picture.jpg").write_bytes(b"source image")
    models = []
    for identity in ("XJ3062|5709", "PJ1239|6184"):
        models.append(dict(
            identity=identity, code=identity.replace("|", "-"), sizes=["S-44"],
            source_files={"source.json": held.packs.file_sha256(tmp_path / "source.json")},
            image_file="picture.jpg", image_sha256=held.packs.file_sha256(tmp_path / "picture.jpg"),
            operation_count=1, rate_per_factory="25.50",
            details_json={"old_erp_migration": {"identity": identity}, "paid_operations": [
                {"sewingFactory": factory, "rate": "25.50"}
                for factory in ("milana", "besttex", "eco_cotton")
            ]},
        ))
    if mutate:
        mutate(models)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"models": models}))
    args = SimpleNamespace(input=tmp_path / "manifest.json")
    payload = {"catalog_manifest_sha256": held.packs.file_sha256(catalog)}
    return args, payload


def test_source_evidence_must_still_match_reviewed_hash(tmp_path):
    args, payload = source_fixture(tmp_path)
    assert len(held.read_catalog(args, payload)) == 2
    (tmp_path / "picture.jpg").write_bytes(b"different image")
    with pytest.raises(ValueError, match="Source evidence changed"):
        held.read_catalog(args, payload)


def test_catalog_manifest_cannot_be_replaced(tmp_path):
    args, payload = source_fixture(tmp_path)
    (tmp_path / "catalog.json").write_text("{}")
    with pytest.raises(ValueError, match="Catalog manifest hash changed"):
        held.read_catalog(args, payload)


def test_unrequested_catalog_identity_is_rejected(tmp_path):
    args, payload = source_fixture(tmp_path, lambda models: models[0].update(identity="XJ3062|9999"))
    with pytest.raises(ValueError, match="Unexpected catalog identities"):
        held.read_catalog(args, payload)


def test_source_operations_must_reconcile_for_every_factory(tmp_path):
    args, payload = source_fixture(tmp_path, lambda models: models[0]["details_json"]["paid_operations"].pop())
    with pytest.raises(ValueError, match="Source operation count/rate mismatch"):
        held.read_catalog(args, payload)


def test_existing_original_variant_blocks_duplicate_creation(tmp_path):
    args, payload = source_fixture(tmp_path)
    catalog = held.read_catalog(args, payload)
    existing = SimpleNamespace(code="OTHER-DISPLAY-CODE", details_json={
        "old_erp_migration": {"identity": "XJ3062|5709"},
        "general": {"model_no": "XJ3062", "variant_no": "5709"},
    })
    db = SimpleNamespace(query=lambda _: SimpleNamespace(all=lambda: [existing]))
    with pytest.raises(ValueError, match="already exists"):
        held.absent_models(db, catalog)

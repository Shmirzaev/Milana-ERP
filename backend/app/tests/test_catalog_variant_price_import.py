from pathlib import Path

from app.db.session import SessionLocal
from app.models import Model
from scripts.apply_catalog_variant_prices import load_manifest, plan_import


def test_reviewed_catalog_price_manifest_is_intact():
    manifest = load_manifest(Path(__file__).resolve().parents[2] / "data" / "catalog-variant-prices-20260902.json")

    assert len(manifest["prices"]) == 1660
    assert manifest["catalog_card_counts"] == {
        "1": 52,
        "2": 76,
        "3": 35,
        "4": 1385,
        "5": 153,
        "6": 48,
    }
    assert manifest["excluded_counts"] == {"missing_positive_price": 36, "missing_variant_no": 25}


def test_price_import_matches_exact_variants_without_creating_models():
    db = SessionLocal()
    try:
        models = [
            Model(code="PRICE-IMPORT-ONE-100", name="One", status="approved", details_json={"general": {"model_no": "PRICE-IMPORT-ONE", "variant_no": "V-100"}}),
            Model(code="PRICE-IMPORT-DUP-200", name="Duplicate old", status="approved", details_json={"general": {"model_no": "PRICE-IMPORT-DUP", "variant_no": "200"}}),
            Model(code="PRICE-IMPORT-DUP-V-200", name="Duplicate new", status="approved", details_json={"general": {"model_no": "PRICE-IMPORT-DUP", "variant_no": "V-200"}}),
        ]
        db.add_all(models)
        db.commit()
        before_count = db.query(Model).count()
        manifest = {
            "data_sha256": "test",
            "prices": [
                {"model_no": "PRICE-IMPORT-ONE", "variant_no": "V-100", "normalized_model_no": "priceimportone", "normalized_variant_no": "100", "selling_price": "4.8", "currency": "USD"},
                {"model_no": "PRICE-IMPORT-DUP", "variant_no": "V-200", "normalized_model_no": "priceimportdup", "normalized_variant_no": "200", "selling_price": "6.3", "currency": "USD"},
                {"model_no": "PRICE-IMPORT-MISSING", "variant_no": "V-300", "normalized_model_no": "priceimportmissing", "normalized_variant_no": "300", "selling_price": "7.1", "currency": "USD"},
            ],
        }

        report, updates = plan_import(db, manifest)

        assert report["matched_identity_count"] == 2
        assert report["matched_model_count"] == 3
        assert report["would_update_count"] == 3
        assert report["missing_count"] == 1
        assert report["duplicate_identity_count"] == 1
        assert db.query(Model).count() == before_count
        assert {model.id for model, _ in updates} == {model.id for model in models}
    finally:
        db.close()

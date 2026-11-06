from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.schemas import Model, ModelImage
from app.models import model_family_images_service as photos
from app.models.model_images_service import warehouse_stock_image_urls


def _model(db, code, general, *, factory=None, scope="standard", legacy=False):
    model = Model(code=code, name=code, catalog_scope=scope, factory_code=factory,
                  details_json={"general": general, "legacy_import": legacy,
                                "technical_payload": "large-unused-data" * 10_000})
    db.add(model)
    db.flush()
    return model


def _image(db, model, suffix, *, primary=False, kind="model"):
    image = ModelImage(model_id=model.id, file_url=f"/storage/model-files/{suffix}.webp",
                       file_name=f"{suffix}.webp", content_type="image/webp", image_type=kind,
                       is_primary=primary, file_data=b"unused-binary-image" * 1000)
    db.add(image)
    db.flush()
    return image


def test_family_projection_preserves_selection_scope_and_excludes_large_payloads(monkeypatch):
    with SessionLocal() as db:
        base = _model(db, "PROJECT-BASE", {"model_no": "PROJECT", "variant_no": ""})
        variant = _model(db, "PROJECT-007", {"modelNo": "PROJECT", "variantNo": "007"})
        newest = _model(db, "PROJECT-008", {"model_no": "PROJECT", "variant_no": "008"})
        eco = _model(db, "PROJECT-ECO", {"model_no": "PROJECT"}, factory="ECO")
        usluga = _model(db, "PROJECT-USLUGA", {"model_no": "PROJECT"}, factory="ECO", scope="usluga")
        legacy = _model(db, "PROJECT-LEGACY", {"model_no": "PROJECT"}, legacy=True)
        primary = _image(db, base, "base-primary", primary=True)
        _image(db, base, "base-newer")
        _image(db, variant, "variant")
        _image(db, newest, "newest-material", kind="material")
        _image(db, eco, "eco")
        _image(db, usluga, "usluga")
        _image(db, legacy, "legacy")
        ids = [row.id for row in (base, variant, newest, eco, usluga, legacy)]
        primary_id = primary.id
        db.commit()
        db.expunge_all()
        models = db.query(Model).options(selectinload(Model.images)).filter(Model.id.in_(ids)).all()
        expected = {photos._family_key(row): photos.family_image_from_members(row, models).id
                    for row in models if not photos._legacy(row)}
        assert expected[photos._family_key(models[0])] == primary_id

        observed = []
        original = photos.family_image_from_members

        def inspect_projected_identity(model, members):
            for member in members:
                assert set(member.details_json) == {"general", "legacy_import"}
                assert "technical_payload" not in member.details_json
                observed.append(member.id)
            return original(model, members)

        monkeypatch.setattr(photos, "family_image_from_members", inspect_projected_identity)
        statements = []

        def capture(connection, clause, *_):
            statements.append(str(clause.compile(dialect=postgresql.dialect())))

        event.listen(db.get_bind(), "before_execute", capture)
        try:
            actual = photos.family_images_for_models(db, models)
        finally:
            event.remove(db.get_bind(), "before_execute", capture)
        assert observed
        assert {key: image.id for key, image in actual.items()} == expected
        family_queries = [sql for sql in statements if "identity_general" in sql]
        assert len(family_queries) == 3  # separate standard/MIL, standard/ECO and Usluga/ECO scopes
        assert all("models.details_json," not in sql.split("FROM")[0] and "model_images.file_data" not in sql
                   for sql in family_queries)
        assert all(" -> " in sql for sql in family_queries)
        urls = warehouse_stock_image_urls(db, ids)
        for model in models:
            expected_image = (photos.own_model_image(model) if photos._legacy(model)
                              else original(model, models))
            assert urls[model.id] == expected_image.file_url


@pytest.mark.parametrize("general", [None, [], "malformed", {}, {"modelNo": "FALLBACK", "variantNo": ""}])
def test_projected_identity_keeps_code_fallback_and_base_precedence(general):
    with SessionLocal() as db:
        base = _model(db, "FALLBACK", general)
        variant = _model(db, "FALLBACK-001", {"model_no": "FALLBACK", "variant_no": "001"})
        expected = _image(db, base, "fallback-base").id
        _image(db, variant, "fallback-variant")
        db.flush()
        actual = photos.family_images_for_models(db, [variant])
        assert actual[photos._family_key(variant)].id == expected


def test_family_projection_cache_refreshes_after_image_changes():
    with SessionLocal() as db:
        base = _model(db, "REFRESH", {"model_no": "REFRESH"})
        variant = _model(db, "REFRESH-001", {"model_no": "REFRESH", "variant_no": "001"})
        first = _image(db, variant, "initial")
        assert photos.model_family_image(variant).id == first.id
        replacement = _image(db, base, "replacement")
        assert photos.model_family_image(variant).id == replacement.id


def test_family_projection_handles_scalar_callers_without_loading_binary_images():
    with SessionLocal() as db:
        base = _model(db, "SCALAR", {"model_no": "SCALAR"})
        image_id = _image(db, base, "scalar-photo").id
        scalar = SimpleNamespace(id=base.id, code=base.code, name=base.name,
                                 details_json=base.details_json, catalog_scope="standard", factory_code=None)
        db.commit()
        db.expunge_all()
        image = photos.family_images_for_models(db, [scalar])[photos._family_key(scalar)]
        assert image.id == image_id
        assert "file_data" not in image.__dict__


def test_bulk_warehouse_images_preserve_evidence_fallback_and_missing_pictures():
    with SessionLocal() as db:
        legacy = _model(db, "LEGACY-EVIDENCE", None, legacy=True)
        _image(db, legacy, "legacy-old", kind="warehouse_package")
        latest = _image(db, legacy, "legacy-new", kind="warehouse_package")
        missing = _model(db, "NO-IMAGE", None)
        _image(db, missing, "material-only", kind="material")
        own = _model(db, "LEGACY-OWN", None, legacy=True)
        own_image = _image(db, own, "own")
        _image(db, own, "evidence", kind="warehouse_package")
        ids = [legacy.id, missing.id, own.id]
        expected = {legacy.id: latest.file_url, missing.id: None, own.id: own_image.file_url}
        db.commit()
        db.expunge_all()
        assert warehouse_stock_image_urls(db, []) == {}
        assert warehouse_stock_image_urls(db, ids + [99999999]) == expected
        assert all(not isinstance(row, Model) for row in db.identity_map.values())
        assert all("file_data" not in row.__dict__ for row in db.identity_map.values())


def test_storage_map_preserves_legacy_aggregation_partial_quantities_and_filters(client, auth_headers):
    from datetime import datetime, timezone
    from app.schemas import LegacyStockReceipt, Package

    with SessionLocal() as db:
        model = _model(db, "STOCK-001", {"model_no": "STOCK", "variant_no": "001"}, legacy=True)
        picture = _image(db, model, "stock-evidence", kind="warehouse_package").file_url
        for index, (kind, status, cell, quantity, dispatched) in enumerate([
            ("standard", "received_in_storage", "A-01", 12, 2),
            ("standard", "received_in_storage", None, 20, 3),
            ("standard", "received_in_storage", None, 10, 0),
            ("standard", "shipped", None, 99, 99),
            ("first_grade", "received_in_storage", None, 1, 0),
        ]):
            receipt = LegacyStockReceipt(source_system="SPEED_TEST", source_warehouse_id="1",
                                         source_record_id=str(index), source_checksum="0" * 64, source_payload={})
            db.add(receipt)
            db.flush()
            db.add(Package(package_no=f"SPEED-{index}", barcode=f"SPEED-QR-{index}", model_id=model.id,
                           legacy_receipt_id=receipt.id, color="Blue", stock_kind=kind, status=status,
                           capacity=quantity, total_quantity=quantity, dispatched_quantity=dispatched,
                           storage_cell=cell, created_at=datetime(2026, 10, 10, 12, tzinfo=timezone.utc)))
        db.commit()
    response = client.get("/api/packages/storage-map?include_unplaced=true&model_query=STOCK", headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"]["packages_in_storage"] == 3
    assert data["summary"]["packages_on_map"] == 1
    assert data["summary"]["matched_packages"] == 3
    assert len(data["placements"]) == 2
    assert sorted(row["total_quantity"] for row in data["placements"]) == [10, 27]
    assert {row["model_image_url"] for row in data["placements"]} == {picture}
    first_grade = client.get("/api/packages/storage-map?include_unplaced=true&stock_kind=first_grade", headers=auth_headers)
    assert first_grade.status_code == 200, first_grade.text
    assert first_grade.json()["summary"]["packages_in_storage"] == 1
    placed = client.get("/api/packages/storage-map", headers=auth_headers)
    assert placed.status_code == 200, placed.text
    assert len(placed.json()["placements"]) == 1
    empty = client.get("/api/packages/storage-map?include_unplaced=true&created_from=2026-10-12", headers=auth_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["placements"] == []

from types import SimpleNamespace

import pytest

from app.db.session import SessionLocal
from app.schemas import CuttingRecord, Department, Model, ModelImage, ProductionOrder, WorkOrder
from app.models.cutting_sheet_service import _sheet_model_image_src
from app.models.label_images_service import model_preview_label_image_src


def image(image_id, image_type="model", primary=False):
    return SimpleNamespace(
        id=image_id,
        image_type=image_type,
        is_primary=primary,
        file_url=f"https://example.com/{image_id}.jpg",
        file_name=f"{image_id}.jpg",
        content_type="image/jpeg",
        file_data=None,
    )


def test_cutting_picture_uses_primary_even_when_other_photos_come_first():
    primary = image(27382, primary=True)
    other = image(27384)
    for images in ([other, primary], [primary, other]):
        assert model_preview_label_image_src(SimpleNamespace(images=images)) == primary.file_url


def test_cutting_picture_keeps_garment_separate_from_print_artwork():
    newest = image(4, "print")
    model = SimpleNamespace(images=[image(3, "print"), image(2, primary=True), newest])
    assert model_preview_label_image_src(model) == "https://example.com/2.jpg"


def test_cutting_picture_does_not_substitute_material_when_model_picture_is_empty():
    assert model_preview_label_image_src(SimpleNamespace(images=[image(1, "material")])) is None
    assert model_preview_label_image_src(None) is None


@pytest.fixture
def model_family():
    with SessionLocal() as db:
        parent = Model(code="PG10527", name="Parent", details_json={"general": {"model_no": "PG10527"}})
        parent.images = [ModelImage(
            file_url="/storage/model-files/parent.png", content_type="image/png",
            file_data=b"parent-picture", image_type="model", is_primary=True,
        )]
        variant = Model(code="PG10527-V-6510", name="Variant", details_json={
            "general": {"model_no": "PG10527", "variant_no": "V-6510"},
        })
        variant.images = [ModelImage(
            file_url="https://example.com/fabric.jpg", content_type="image/jpeg", image_type="material",
        )]
        db.add_all([parent, variant])
        db.commit()
        yield db, parent, variant


@pytest.mark.parametrize("production_type", ["branded_stock", "usluga"])
@pytest.mark.parametrize("has_variant_fabric", [True, False])
def test_cutting_sheet_endpoint_uses_parent_garment_and_variant_fabric(
    model_family, client, auth_headers, production_type, has_variant_fabric,
):
    db, parent, variant = model_family
    if production_type == "usluga":
        parent.catalog_scope = variant.catalog_scope = "usluga"
        parent.factory_code = variant.factory_code = "ECO"
    parent.images.append(ModelImage(
        file_url="https://example.com/parent-fabric.jpg", content_type="image/jpeg", image_type="material",
    ))
    if not has_variant_fabric:
        variant.images.clear()
    variant.details_json = {**variant.details_json, "composition": [{"name": "Cotton", "percentage": 95}, {"name": "Elastane", "percentage": 5}]}
    order = ProductionOrder(production_no="PO-PARENT-PHOTO", production_type=production_type, model_id=variant.id)
    db.add(order)
    db.flush()
    work = WorkOrder(
        production_order_id=order.id, operation="cutting",
        department_id=db.query(Department).filter(Department.code == "CUT").one().id,
    )
    db.add(work)
    db.flush()
    record = CuttingRecord(work_order_id=work.id)
    db.add(record)
    db.commit()

    response = client.get(f"/api/cutting/records/{record.id}/production-sheet", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert "src='data:image/png;base64,cGFyZW50LXBpY3R1cmU=' alt='Model image'" in response.text
    if has_variant_fabric:
        assert "src='https://example.com/fabric.jpg' alt='Fabric picture'" in response.text
    else:
        assert "alt='Fabric picture'" not in response.text
    assert "parent-fabric.jpg" not in response.text
    assert "Cotton 95% / Elastane 5%" in response.text
    assert "<div class='empty-photo'></div>" not in response.text


@pytest.mark.parametrize("image_type", ["model", "print"])
def test_cutting_sheet_prefers_parent_over_variant_photo_or_print_override(model_family, image_type):
    db, _, variant = model_family
    variant.images.append(ModelImage(
        file_url="https://example.com/variant.jpg", content_type="image/jpeg",
        image_type=image_type, is_primary=True,
    ))
    db.flush()
    assert _sheet_model_image_src(db, variant) == "data:image/png;base64,cGFyZW50LXBpY3R1cmU="


@pytest.mark.parametrize("condition", ["missing", "material_only", "scope", "factory", "no_link"])
def test_cutting_sheet_does_not_borrow_unrelated_or_fabric_photos(model_family, condition):
    db, parent, variant = model_family
    if condition == "missing":
        parent.code = "OTHER-PARENT"
        parent.details_json = {"general": {"model_no": "OTHER-PARENT"}}
    elif condition == "material_only":
        parent.images[0].image_type = "material"
    elif condition == "scope":
        parent.catalog_scope = "usluga"
        parent.factory_code = variant.factory_code = "ECO"
    elif condition == "factory":
        parent.factory_code = "BST"
    else:
        variant.details_json = None
    db.flush()
    assert _sheet_model_image_src(db, variant) is None


def test_cutting_sheet_resolves_legacy_camel_case_parent_picture(model_family):
    db, _, variant = model_family
    variant.details_json = {"general": {"modelNo": "PG10527", "variantNo": "V-6510"}}
    assert _sheet_model_image_src(db, variant) == "data:image/png;base64,cGFyZW50LXBpY3R1cmU="


@pytest.mark.parametrize("condition", ["missing_parent", "empty_parent", "material_parent", "standalone"])
def test_cutting_sheet_retains_own_garment_without_parent_photo(model_family, condition):
    db, parent, variant = model_family
    if condition == "missing_parent":
        parent.code = "OTHER-PARENT"
        parent.details_json = {"general": {"model_no": "OTHER-PARENT"}}
    elif condition == "empty_parent":
        parent.images.clear()
    elif condition == "material_parent":
        parent.images[0].image_type = "material"
    else:
        variant.details_json = {"general": {"model_no": variant.code}}
    variant.images.append(ModelImage(
        file_url="https://example.com/own.jpg", content_type="image/jpeg", image_type="model",
    ))
    db.flush()
    assert _sheet_model_image_src(db, variant) == "https://example.com/own.jpg"


def test_cutting_sheet_missing_parent_file_does_not_substitute_variant(model_family):
    db, parent, variant = model_family
    parent.images[0].file_data = None
    variant.images.append(ModelImage(
        file_url="https://example.com/own.jpg", content_type="image/jpeg", image_type="model",
    ))
    db.flush()
    assert _sheet_model_image_src(db, variant) is None


def test_cutting_sheet_without_model_has_no_garment(model_family):
    db, _, _ = model_family
    assert _sheet_model_image_src(db, None) is None


def test_cutting_sheet_shares_garment_from_same_family_sibling(model_family):
    db, sibling, variant = model_family
    sibling.details_json = {"general": {"model_no": "PG10527", "variant_no": "V-6511"}}
    db.flush()
    assert _sheet_model_image_src(db, variant) == "data:image/png;base64,cGFyZW50LXBpY3R1cmU="

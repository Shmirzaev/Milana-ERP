from types import SimpleNamespace

from app.db.session import SessionLocal
from app.models import Item, Model, ModelBOM, ModelImage
from app.services.cutting_sheet import _fabric_composition, _composition_text
from app.services.model_images import model_display_image_url, model_variant_picture_url
from app.services.label_images import variant_label_image_src


def test_shared_material_never_fills_missing_model_or_variant_picture():
    model = SimpleNamespace(images=[], bom=[SimpleNamespace(
        id=1, photo_url="https://example.com/bom.png",
        item=SimpleNamespace(category="fabric", image_url="https://example.com/item.png"),
        stock_batch=SimpleNamespace(image_url="https://example.com/batch.png"),
    )])
    assert model_display_image_url(model) is None
    assert model_variant_picture_url(model) is None
    assert variant_label_image_src(model) is None


def test_parent_and_new_variants_keep_independent_uploads(client, auth_headers):
    with SessionLocal() as db:
        parent = Model(code="ISOLATION", name="Isolated family", details_json={"general": {"model_no": "ISOLATION"}})
        parent.images = [ModelImage(file_url="https://example.com/parent.png", image_type="model", is_primary=True)]
        fabric = Item(sku="ISOLATION-FABRIC", name="Shared fabric", category="fabric", unit="kg", image_url="https://example.com/shared.png")
        db.add_all([parent, fabric])
        db.flush()
        db.add(ModelBOM(model_id=parent.id, item_id=fabric.id, unit="kg", quantity_per_piece=1, photo_url="https://example.com/bom.png"))
        db.commit()
        parent_id = parent.id
    first = client.post(f"/api/models/{parent_id}/variants", headers=auth_headers, json={"variant_no": "101"})
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    detail = client.get(f"/api/models/{first_id}", headers=auth_headers).json()
    assert detail["images"] == []
    assert client.get(f"/api/models/{parent_id}/variants", headers=auth_headers).json()[0]["picture_url"] is None
    upload = client.post(f"/api/models/{first_id}/images", headers=auth_headers, json={
        "file_url": "https://example.com/first.png", "image_type": "material",
    })
    assert upload.status_code == 201, upload.text
    second = client.post(f"/api/models/{first_id}/variants", headers=auth_headers, json={"variant_no": "102"})
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    assert client.get(f"/api/models/{second_id}", headers=auth_headers).json()["images"] == []
    for compact in ("true", "false"):
        group = client.get("/api/models/variant-groups", headers=auth_headers, params={"q": "ISOLATION", "compact": compact, "include_total": "true"}).json()["rows"][0]
        assert group["id"] == parent_id
        assert group["primary_image_url"] == "https://example.com/parent.png"
        variants = {v["model_id"]: v["picture_url"] for v in group["variants"]}
        assert variants == {first_id: "https://example.com/first.png", second_id: None}
    with SessionLocal() as db:
        db.query(ModelImage).filter(ModelImage.model_id == parent_id).delete()
        db.commit()
    group = client.get("/api/models/variant-groups", headers=auth_headers, params={"q": "ISOLATION", "include_total": "true"}).json()["rows"][0]
    assert group["primary_image"] is None
    assert group["primary_image_url"] is None
    copied = client.post(f"/api/models/{first_id}/clone", headers=auth_headers)
    assert copied.status_code == 201, copied.text
    assert client.get(f"/api/models/{copied.json()['id']}", headers=auth_headers).json()["images"] == []


def test_cutting_composition_uses_actual_fabric_then_model_and_handles_blanks():
    model = SimpleNamespace(details_json={"composition": [{"name": "Cotton", "percentage": 95}, {"name": "Elastane", "percentage": 5}]}, material_composition=[])
    batch = SimpleNamespace(item=SimpleNamespace(composition_json=[{"name": "Viscose", "percentage": 100}]))
    assert _fabric_composition(model, batch) == "Viscose 100%"
    assert _fabric_composition(model, None) == "Cotton 95% / Elastane 5%"
    assert _fabric_composition(None, None) == ""
    assert _composition_text([None, {"name": ""}, {"name": "Cotton", "percentage": "bad"}]) == "Cotton"

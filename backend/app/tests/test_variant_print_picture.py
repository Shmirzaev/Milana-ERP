from uuid import uuid4

from app.models import Item, Model, ModelBOM
from app.services.model_images import material_preview_image_url, model_preview_image_url
from app.tests.conftest import TestSessionLocal


def test_variant_artwork_is_exact_preserved_and_used_in_workflow(client, auth_headers):
    with TestSessionLocal() as db:
        model = Model(code=f"PRINT-{uuid4().hex[:8]}", name="Print model", status="approved",
                      details_json={"general": {"model_no": "PRINT-TEST"}})
        item = db.query(Item).filter(Item.category == "fabric").first()
        db.add(model); db.flush()
        db.add(ModelBOM(model_id=model.id, item_id=item.id, color="blue", unit="kg", quantity_per_piece=1,
                        photo_url="/storage/model-files/fabric.png"))
        db.commit(); mid = model.id
    created = client.post(f"/api/models/{mid}/variants", json={"variant_no": "PRINT-A",
                          "picture_url": "/storage/model-files/fabric.png", "print_picture_url": "/storage/model-files/artwork.png"}, headers=auth_headers)
    assert created.status_code == 201, created.text
    variant_id = created.json()["id"]
    variants = client.get(f"/api/models/{mid}/variants", headers=auth_headers).json()
    actual = next(row for row in variants if row["id"] == variant_id)
    assert actual["print_picture_url"].split("?")[0] == "/storage/model-files/artwork.png"
    assert actual["picture_url"].split("?")[0] == "/storage/model-files/fabric.png"
    with TestSessionLocal() as db:
        variant = db.get(Model, variant_id)
        assert model_preview_image_url(variant) == "/storage/model-files/artwork.png"
        assert material_preview_image_url(variant) == "/storage/model-files/fabric.png"
        assert model_preview_image_url(db.get(Model, mid)) != "/storage/model-files/artwork.png"
    changed = client.patch(f"/api/models/{mid}/variants/{variant_id}", json={"variant_no": "PRINT-A", "color": "red"}, headers=auth_headers)
    assert changed.status_code == 200, changed.text
    sibling = client.post(f"/api/models/{variant_id}/variants", json={"variant_no": "PRINT-B"}, headers=auth_headers)
    assert sibling.status_code == 201, sibling.text
    sibling_detail = client.get(f"/api/models/{sibling.json()['id']}", headers=auth_headers).json()
    assert not any(image["image_type"] == "print" for image in sibling_detail["images"])
    with TestSessionLocal() as db:
        assert model_preview_image_url(db.get(Model, variant_id)) == "/storage/model-files/artwork.png"
    removed = client.patch(f"/api/models/{mid}/variants/{variant_id}", json={"variant_no": "PRINT-A", "print_picture_url": None}, headers=auth_headers)
    assert removed.status_code == 200, removed.text
    with TestSessionLocal() as db:
        assert model_preview_image_url(db.get(Model, variant_id)) != "/storage/model-files/artwork.png"

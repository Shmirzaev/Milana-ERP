from types import SimpleNamespace

from app.services.label_images import model_preview_label_image_src


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


def test_cutting_picture_respects_the_pages_latest_print_override():
    newest = image(4, "print")
    model = SimpleNamespace(images=[image(3, "print"), image(2, primary=True), newest])
    assert model_preview_label_image_src(model) == newest.file_url


def test_cutting_picture_does_not_substitute_material_when_model_picture_is_empty():
    assert model_preview_label_image_src(SimpleNamespace(images=[image(1, "material")])) is None
    assert model_preview_label_image_src(None) is None

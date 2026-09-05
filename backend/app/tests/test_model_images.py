from types import SimpleNamespace

from app.services.label_images import fabric_label_image_src
from app.services.model_images import material_preview_image_url, warehouse_stock_image_url


def _fabric_bom(row_id: int, photo_url: str):
    return SimpleNamespace(
        id=row_id,
        photo_url=photo_url,
        stock_batch=None,
        item=SimpleNamespace(category="fabric", image_url=None),
    )


def test_material_preview_uses_original_bom_order():
    model = SimpleNamespace(
        bom=[
            _fabric_bom(44, "/storage/model-files/burgundy.jpg"),
            _fabric_bom(43, "/storage/model-files/dark-blue.jpg"),
        ],
        images=[],
    )

    assert material_preview_image_url(model) == "/storage/model-files/dark-blue.jpg"


def test_material_preview_prefers_exact_variant_material_image_over_shared_bom():
    model = SimpleNamespace(
        bom=[_fabric_bom(43, "/storage/model-files/shared-fabric.jpg")],
        images=[
            SimpleNamespace(
                id=91,
                file_url="/storage/model-files/exact-variant.jpg",
                file_name="exact-variant.jpg",
                content_type="image/jpeg",
                image_type="material",
                is_primary=False,
            )
        ],
    )

    assert material_preview_image_url(model) == "/storage/model-files/exact-variant.jpg"


def test_fabric_label_prefers_exact_variant_material_image_over_shared_bom():
    model = SimpleNamespace(
        bom=[_fabric_bom(43, "https://example.com/shared-fabric.jpg")],
        images=[
            SimpleNamespace(
                id=91,
                file_url="https://example.com/exact-variant.jpg",
                file_name="exact-variant.jpg",
                content_type="image/jpeg",
                file_data=None,
                image_type="material",
                is_primary=False,
            )
        ],
    )

    assert fabric_label_image_src(model) == "https://example.com/exact-variant.jpg"


def _image(row_id: int, image_type: str, url: str):
    return SimpleNamespace(
        id=row_id,
        file_url=url,
        file_name=url.rsplit("/", 1)[-1],
        content_type="image/jpeg",
        image_type=image_type,
        is_primary=False,
    )


def test_warehouse_stock_uses_legacy_package_picture_as_last_resort():
    model = SimpleNamespace(
        bom=[],
        images=[_image(92, "warehouse_package", "/storage/model-files/legacy-stock.jpg")],
    )

    assert warehouse_stock_image_url(model) == "/storage/model-files/legacy-stock.jpg"


def test_warehouse_stock_prefers_catalog_picture_over_legacy_package_picture():
    model = SimpleNamespace(
        bom=[],
        images=[
            _image(92, "warehouse_package", "/storage/model-files/legacy-stock.jpg"),
            _image(91, "model", "/storage/model-files/catalog-model.jpg"),
        ],
    )

    assert warehouse_stock_image_url(model) == "/storage/model-files/catalog-model.jpg"

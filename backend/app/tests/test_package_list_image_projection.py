from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models import Model, ModelImage, Package, ProductionOrder
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("image_count", [1, 50, 401])
def test_package_list_loads_image_metadata_without_blob(client, auth_headers, image_count):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        model = Model(
            code=f"PERF35-PACKAGE-LIST-{marker}",
            name="Package list image projection",
            status="approved",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF35-PACKAGE-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=10,
        )
        db.add(order)
        urls = []
        for index in range(image_count):
            url = f"https://images.example.invalid/package-list-{marker}-{index}.webp"
            urls.append(url)
            db.add(
                ModelImage(
                    model_id=model.id,
                    file_url=url,
                    file_name=f"image-{index}.webp",
                    content_type="image/webp",
                    image_type="model",
                    is_primary=True,
                    file_data=b"large model image binary not needed by package list",
                )
            )
        db.flush()
        package = Package(
            package_no=f"PERF35-PACKAGE-{marker}",
            barcode=f"PERF35-PACKAGE-QR-{marker}",
            qr_code_url="https://images.example.invalid/package-qr.png",
            production_order_id=order.id,
            model_id=model.id,
            color="BLUE",
            package_type="bag",
            total_quantity=10,
            capacity=60,
            status="packed",
            packaging_department_code="PKG",
        )
        db.add(package)
        db.commit()
        production_order_id = int(order.id)
        package_no = package.package_no
        expected_url = urls[-1]
        engine = db.bind

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/packages",
            params={
                "production_order_id": production_order_id,
                "page": 1,
                "page_size": 1,
                "include_total": "true",
            },
            headers=auth_headers,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    row = next(row for row in response.json()["rows"] if row["package_no"] == package_no)
    assert row["model_image_url"] == expected_url
    image_reads = [statement for statement in statements if " from model_images " in statement]
    assert len(image_reads) == 1
    assert "model_images.file_data" not in image_reads[0]

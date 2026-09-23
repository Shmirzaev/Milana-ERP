from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.packages import storage_map
from app.models import LegacyStockReceipt, Model, ModelImage, Package
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("model_count", [1, 50, 401])
def test_storage_map_selects_image_metadata_without_binary_at_constant_query_count(model_count):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        models = [
            Model(
                code=f"PERF35-MAP-{marker}-{index}",
                name=f"Storage map model {index}",
                status="approved",
            )
            for index in range(model_count)
        ]
        db.add_all(models)
        db.flush()
        expected_urls = {}
        for index, model in enumerate(models):
            url = f"https://images.example.invalid/storage-map-{marker}-{index}.webp"
            expected_urls[int(model.id)] = url
            receipt = LegacyStockReceipt(
                source_system="PERF35",
                source_warehouse_id="MAP",
                source_record_id=f"{marker}-{index}",
                source_checksum=sha256(f"{marker}-{index}".encode()).hexdigest(),
                source_payload={"index": index},
            )
            db.add(receipt)
            db.flush()
            db.add_all(
                [
                    ModelImage(
                        model_id=model.id,
                        file_url=url,
                        file_name="primary.webp",
                        content_type="image/webp",
                        image_type="model",
                        is_primary=True,
                        file_data=b"large image binary not needed by warehouse map",
                    ),
                    Package(
                        package_no=f"PERF35-MAP-PKG-{marker}-{index}",
                        barcode=f"PERF35-MAP-QR-{marker}-{index}",
                        legacy_receipt_id=receipt.id,
                        model_id=model.id,
                        color="BLUE",
                        package_type="legacy_stock",
                        total_quantity=5,
                        capacity=60,
                        status="received_in_storage",
                    ),
                ]
            )
        db.commit()

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = storage_map(db, None, include_unplaced=True)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    actual_urls = {
        int(row["model_id"]): row["model_image_url"]
        for row in result["placements"]
    }
    assert actual_urls == expected_urls
    assert len(statements) == 6
    assert len(image_reads) == 1
    assert "model_images.file_data" not in image_reads[0]

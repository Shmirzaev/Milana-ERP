from hashlib import sha256
from uuid import uuid4

from sqlalchemy import event

from app.api.routes.packages import storage_map
from app.models import Item, LegacyStockReceipt, Model, ModelBOM, Package
from app.tests.conftest import TestSessionLocal


def test_storage_map_projects_only_bom_image_fallback_fields():
    marker = uuid4().hex[:8]
    image_url = f"https://images.example.invalid/bom-{marker}.webp"
    with TestSessionLocal() as db:
        model = Model(code=f"PERF35-BOM-{marker}", name="BOM fallback", status="approved")
        item = Item(
            sku=f"PERF35-BOM-I-{marker}",
            name="Fallback fabric",
            category="fabric",
            unit="m",
            image_url=image_url,
            composition_json=[{"name": "cotton", "percentage": 100}],
        )
        db.add_all([model, item])
        db.flush()
        db.add(ModelBOM(
            model_id=model.id,
            item_id=item.id,
            quantity_per_piece=1.25,
            unit="m",
            waste_percent=4,
        ))
        receipt = LegacyStockReceipt(
            source_system="PERF35",
            source_warehouse_id="MAP",
            source_record_id=marker,
            source_checksum=sha256(marker.encode()).hexdigest(),
            source_payload={"marker": marker},
        )
        db.add(receipt)
        db.flush()
        db.add(Package(
            package_no=f"PERF35-BOM-PKG-{marker}",
            barcode=f"PERF35-BOM-QR-{marker}",
            legacy_receipt_id=receipt.id,
            model_id=model.id,
            color="BLUE",
            package_type="box",
            total_quantity=2,
            capacity=60,
            status="received_in_storage",
            storage_cell="A-01",
        ))
        db.commit()

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = storage_map(db, None)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert [row["model_image_url"] for row in result["placements"]] == [image_url]
    bom_reads = [statement for statement in statements if " from model_bom " in statement]
    assert len(bom_reads) == 1
    for unused_column in (
        "model_bom.quantity_per_piece",
        "model_bom.waste_percent",
        "items.composition_json",
        "stock_batches.processes",
    ):
        assert unused_column not in bom_reads[0]

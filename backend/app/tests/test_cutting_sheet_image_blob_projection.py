import base64
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models import CuttingRecord, ModelImage, ProductionOrder, WorkOrder
from app.services.cutting_sheet import render_cutting_sheet_html
from app.tests.conftest import TestSessionLocal
from app.tests.test_production_flow import _create_bundle_for_scan


@pytest.mark.parametrize("image_count", [1, 50, 401])
def test_cutting_sheet_loads_only_selected_model_image_blob(client, auth_headers, image_count):
    bundle = _create_bundle_for_scan(client, auth_headers)
    marker = uuid4().hex[:10]
    image_bytes = f"selected-cutting-sheet-image-{marker}".encode()
    with TestSessionLocal() as db:
        order = db.get(ProductionOrder, bundle["production_order_id"])
        model_id = order.model_id
        for index in range(image_count):
            db.add(
                ModelImage(
                    model_id=model_id,
                    file_url=f"/storage/model-files/cutting-sheet-{marker}-{index}.webp",
                    file_name=f"image-{index}.webp",
                    content_type="image/webp",
                    image_type="model" if index == 0 else "other",
                    is_primary=index == 0,
                    file_data=image_bytes if index == 0 else b"unselected image BLOB",
                )
            )
        work_order = db.query(WorkOrder).filter_by(
            production_order_id=order.id,
            operation="cutting",
        ).first()
        record = CuttingRecord(work_order_id=work_order.id, cut_pieces=10, passed_pieces=10)
        db.add(record)
        db.flush()
        record_id = int(record.id)
        db.commit()

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            html = render_cutting_sheet_html(db, db.get(CuttingRecord, record_id))
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    blob_reads = [statement for statement in image_reads if "model_images.file_data" in statement]
    bundle_reads = [statement for statement in statements if " from bundles " in statement]
    assert f"data:image/webp;base64,{base64.b64encode(image_bytes).decode()}" in html
    assert len(image_reads) == 2
    assert len(blob_reads) == 1
    assert "model_images.id in (?)" in blob_reads[0]
    assert len(bundle_reads) == 2
    assert any("sum(bundles.quantity)" in statement for statement in bundle_reads)
    assert any("bundles.sewing_factory_code" in statement for statement in bundle_reads)

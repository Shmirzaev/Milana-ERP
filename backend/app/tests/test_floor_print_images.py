from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.api.routes import inbox
from app.core.signing import verify_path
from app.models.production.floor_print_images_service import floor_print_image_url
from app.schemas import Department, Model, ModelImage, ProductionBatch, ProductionOrder, SalesOrder, WorkOrder
from app.tests.conftest import TestSessionLocal


def _assert_signed(url, path):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert parsed.path == path
    assert verify_path(parsed.path, query["exp"][0], query["sig"][0])


@pytest.mark.parametrize("attachment", [
    {"file_url": "/storage/sales-order-files/image.png", "content_type": "IMAGE/PNG"},
    {"file_url": "/storage/sales-order-files/image.png?exp=1&sig=expired"},
    {"file_url": "/storage/sales-order-files/image", "content_type": "image/webp"},
    {"file_url": "/storage/sales-order-files/image.bmp", "content_type": "application/octet-stream"},
    {"file_url": "/storage/sales-order-files/image.tiff"},
])
def test_artwork_image_is_signed_with_fresh_signature(attachment):
    url = floor_print_image_url(None, [attachment])
    _assert_signed(url, attachment["file_url"].split("?")[0])


@pytest.mark.parametrize("attachments", [
    None, [], [None, "malformed", {}],
    [{"file_url": "/storage/sales-order-files/file.pdf", "content_type": "application/pdf"}],
    [{"file_url": "/storage/sales-order-files/fake.png", "content_type": "application/pdf"}],
    [{"file_url": "/storage/sales-order-files/instructions.pdf", "content_type": "image/png"}],
    [{"file_url": "", "content_type": "image/png"}],
])
def test_missing_nonimage_or_malformed_artwork_has_no_picture(attachments):
    assert floor_print_image_url(None, attachments) is None


def test_nonimage_attachments_are_skipped_before_image_and_exact_model_fallback():
    model = SimpleNamespace(images=[SimpleNamespace(id=1, image_type="print", file_url="/storage/model-files/exact.png", content_type="image/png")])
    document = {"file_url": "/storage/sales-order-files/instructions.pdf", "content_type": "application/pdf"}
    assert floor_print_image_url(model, [document]) == "/storage/model-files/exact.png"
    _assert_signed(floor_print_image_url(model, [document, {"file_url": "/storage/sales-order-files/art.png"}]),
                   "/storage/sales-order-files/art.png")


def _image(db, model, name, image_type):
    db.add(ModelImage(model_id=model.id, file_url=f"/storage/model-files/{name}.png", file_name=f"{name}.png",
                      content_type="image/png", image_type=image_type, is_primary=True))


def test_context_keeps_exact_order_artwork_and_model_material_pictures_without_writes():
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        models = [Model(code=f"FLOOR-{suffix}-{i}", name=f"Variant {i}") for i in range(3)]
        db.add_all(models)
        db.flush()
        for i, model in enumerate(models):
            _image(db, model, f"garment-{suffix}-{i}", "model")
            _image(db, model, f"material-{suffix}-{i}", "material")
        _image(db, models[0], f"print-{suffix}-0", "print")
        _image(db, models[1], f"print-{suffix}-1", "print")
        sales = SalesOrder(order_no=f"FLOOR-SO-{suffix}", printing_attachments=[
            {"file_url": f"/storage/sales-order-files/customer-{suffix}.png", "content_type": "image/png"}])
        db.add(sales)
        db.flush()
        orders = [ProductionOrder(production_no=f"FLOOR-PO-{suffix}-{i}", production_type="client_order",
                                   model_id=model.id, planned_quantity=10) for i, model in enumerate(models)]
        orders[0].sales_order_id = sales.id
        orders[0].printing_attachments = [{"file_url": "/storage/sales-order-files/po-fallback.png"}]
        orders[1].printing_attachments = [{"file_url": "/storage/sales-order-files/only.pdf", "content_type": "application/pdf"}]
        db.add_all(orders)
        db.commit()
        ids = [p.id for p in orders]
        context = inbox._production_context_by_production_order(db, ids)
        _assert_signed(context[ids[0]]["print_image_url"], f"/storage/sales-order-files/customer-{suffix}.png")
        assert context[ids[1]]["print_image_url"] == f"/storage/model-files/print-{suffix}-1.png"
        assert context[ids[2]]["print_image_url"] is None
        assert all(context[pid]["model_image_url"] for pid in ids)
        materials = inbox._material_payload_by_production_order(db, ids)
        assert all(materials[pid]["material_image_url"] == f"/storage/model-files/material-{suffix}-{i}.png"
                   for i, pid in enumerate(ids))
        assert not db.new and not db.dirty and not db.deleted
        db.expire_all()
        assert db.get(SalesOrder, sales.id).printing_attachments[0]["file_url"] == f"/storage/sales-order-files/customer-{suffix}.png"
        assert inbox._production_context_for_po({}, None)["print_image_url"] is None


def test_same_model_different_orders_do_not_share_order_artwork():
    with TestSessionLocal() as db:
        model = db.query(Model).first()
        orders = [ProductionOrder(production_no=f"FLOOR-OWN-{i}", production_type="client_order", model_id=model.id,
                                  printing_attachments=[{"file_url": f"/storage/sales-order-files/order-{i}.png"}])
                  for i in range(2)]
        db.add_all(orders)
        db.flush()
        context = inbox._production_context_by_production_order(db, [p.id for p in orders])
        for i, order in enumerate(orders):
            _assert_signed(context[order.id]["print_image_url"], f"/storage/sales-order-files/order-{i}.png")


def test_cutting_and_department_pages_project_artwork_only_after_access_check(client, auth_headers):
    with TestSessionLocal() as db:
        model = db.query(Model).first()
        order = ProductionOrder(production_no="FLOOR-API", production_type="client_order", model_id=model.id,
                                status="cutting", printing_attachments=[{"file_url": "/storage/sales-order-files/floor-api.png"}])
        db.add(order)
        db.flush()
        for dept_code, operation in [("CUT", "cutting"), ("PRT", "printing")]:
            dept = db.query(Department).filter_by(code=dept_code).one()
            db.add(WorkOrder(production_order_id=order.id, department_id=dept.id, operation=operation,
                             status="pending", planned_output_qty=10))
        db.commit()
        po_id = order.id
    for path in ["/api/inbox/cutting-orders?dept=CUT", "/api/inbox/department-orders?dept=PRT"]:
        assert client.get(path).status_code == 401
        response = client.get(path, headers=auth_headers)
        assert response.status_code == 200, response.text
        row = next(row for row in response.json()["rows"] if row["production_order_id"] == po_id)
        _assert_signed(row["print_image_url"], "/storage/sales-order-files/floor-api.png")
    # The seeded MIL admin cannot obtain ECO floor projections by changing dept.
    response = client.get("/api/inbox/cutting-orders?dept=ECT", headers=auth_headers)
    assert response.status_code == 403


def test_awaiting_packaging_keeps_batch_identity_and_order_artwork(client, auth_headers):
    with TestSessionLocal() as db:
        model = db.query(Model).first()
        order = ProductionOrder(production_no="FLOOR-PACK", production_type="client_order", model_id=model.id,
                                printing_attachments=[{"file_url": "/storage/sales-order-files/pack.png"}])
        db.add(order)
        db.flush()
        batches = [ProductionBatch(production_order_id=order.id, batch_no=f"B{i}", batch_index=i + 1) for i in range(2)]
        db.add_all(batches)
        db.flush()
        for batch in batches:
            for code, operation, qty in [("SEW", "sewing", 10), ("PKG", "packaging", 2)]:
                dept = db.query(Department).filter_by(code=code).one()
                db.add(WorkOrder(production_order_id=order.id, production_batch_id=batch.id, department_id=dept.id,
                                 operation=operation, status="in_progress", passed_qty=qty))
        db.commit()
        batch_ids = {batch.id for batch in batches}
        po_id = order.id
    response = client.get("/api/inbox/awaiting-packaging?dept=PKG&page_size=50", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = [row for row in response.json()["rows"] if row["production_order_id"] == po_id]
    assert {row["production_batch_id"] for row in rows} == batch_ids
    for row in rows:
        _assert_signed(row["print_image_url"], "/storage/sales-order-files/pack.png")
        assert row["ready_qty"] == 8
